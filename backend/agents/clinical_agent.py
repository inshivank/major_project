"""Clinical Record Analysis agent: local EHR lookup and trained model risk scores."""

from __future__ import annotations

from collections.abc import Sequence
from functools import lru_cache
from pathlib import Path

import pandas as pd

from backend.agents.base import AgentResult
from backend.agents.patient_agent import EMERGENCY_ANSWER, is_emergency
from backend.config.settings import PROJECT_ROOT, settings
from backend.llm.llm_service import LLMError, LLMService
from backend.rag.retriever import RetrievedChunk, Retriever
from backend.schemas.chat import ChatRequest, Intent, Source, SourceType

PREDICTION_DIR = PROJECT_ROOT / "predictions"
RECORDS_PATH = PROJECT_ROOT / "data" / "processed" / "mimic_demo_formatted.csv"

TASKS = {
    "outcome": "In-hospital mortality",
    "readmission": "30-day readmission",
}
MODELS = ("RETAIN", "AdaCare", "MCGRU")

RETRIEVAL_QUERY = (
    "when to seek urgent care warning signs discharge planning follow-up patient safety"
)

SYSTEM_PROMPT = (
    "Write a brief explanation for a clinician using only the risk bands and reference "
    "passages supplied. Use 2-3 short sentences for mortality and 2-3 for readmission, "
    "then one sentence comparing the models. Do not use headings, percentages, patient "
    "details, identifiers, or raw values. Cite passages as [1], [2]. Keep under 90 words "
    "and add a safety caveat."
)


@lru_cache(maxsize=8)
def _load_predictions(directory: str) -> dict[tuple[str, str], dict[str, float]]:
    predictions: dict[tuple[str, str], dict[str, float]] = {}
    root = Path(directory)
    for task in TASKS:
        for model in MODELS:
            path = root / f"mimic_{task}_{model.lower()}.pkl"
            if not path.is_file():
                continue
            payload = pd.read_pickle(path)
            predictions[(task, model)] = {
                str(key): float(value) for key, value in payload.items()
            }
    return predictions


@lru_cache(maxsize=8)
def _load_records(path: str) -> pd.DataFrame | None:
    file = Path(path)
    if not file.is_file():
        return None
    return pd.read_csv(file)


def _risk_band(score: float) -> str:
    if score < 0.2:
        return "low"
    if score < 0.5:
        return "moderate"
    return "high"


def _resolve_record_id(
    patient_id: str, records: pd.DataFrame | None, known: set[str]
) -> str | None:
    requested = str(patient_id).strip()
    if requested in known:
        return requested
    if records is None or records.empty:
        return None
    for column in ("PatientID", "AdmissionID"):
        if column not in records.columns:
            continue
        matches = (
            records.loc[records[column].astype(str) == requested, "RecordID"]
            .dropna()
            .astype(str)
            .unique()
        )
        for record_id in reversed(matches.tolist()):
            if record_id in known:
                return record_id
    return None


def _format_value(value: object) -> str:
    if isinstance(value, float):
        return f"{value:.0f}" if value.is_integer() else f"{value:.1f}"
    return str(value)


def _display_value(label: str, value: object) -> str:
    text = _format_value(value)
    return f"{text}%" if label == "SpO₂" else text


def _patient_line(records: pd.DataFrame | None, record_id: str) -> str:
    parts = [f"Record {record_id}"]
    if records is None or records.empty or "RecordID" not in records.columns:
        return " · ".join(parts + ["stored EHR details unavailable"])
    rows = records.loc[records["RecordID"].astype(str) == record_id]
    if rows.empty:
        return " · ".join(parts + ["stored EHR details unavailable"])
    latest = rows.iloc[-1]
    for column, label in (
        ("Age", "Age"),
        ("Sex", "Sex"),
        ("Heart Rate", "HR"),
        ("Oxygen saturation", "SpO₂"),
    ):
        if column in rows.columns and pd.notna(latest[column]):
            parts.append(f"{label} {_display_value(label, latest[column])}")
    parts.append(f"{len(rows)} hourly records")
    return " · ".join(parts)


def _record_source(records: pd.DataFrame | None, record_id: str) -> Source | None:
    if records is None or records.empty or "RecordID" not in records.columns:
        return None
    rows = records.loc[records["RecordID"].astype(str) == record_id]
    if rows.empty:
        return None
    latest = rows.iloc[-1]
    fields: list[str] = []
    for column, label in (
        ("Age", "Age"),
        ("Sex", "Sex"),
        ("Heart Rate", "HR"),
        ("Oxygen saturation", "SpO₂"),
    ):
        if column in rows.columns and pd.notna(latest[column]):
            fields.append(f"{label} {_display_value(label, latest[column])}")
    detail = "; ".join(fields) if fields else "no numeric observations stored"
    snippet = f"{len(rows)} hourly records; latest {detail}."
    return Source(
        type=SourceType.RECORD,
        title=f"EHR record {record_id}",
        snippet=snippet[:300],
    )


def _band_sentence(task: str, band: str) -> str:
    if task == "outcome":
        return {
            "low": "Low risk band. This suggests a lower estimated chance of death during admission. Continue routine monitoring.",
            "moderate": "Moderate risk band. This suggests a noticeable but not highest-level risk during admission. Interpret with the full clinical picture.",
            "high": "High risk band. This suggests a substantially elevated risk during admission. Consider senior clinical review.",
        }[band]
    return {
        "low": "Low risk band. This suggests a lower chance of returning within 30 days. Standard follow-up is reasonable.",
        "moderate": "Moderate risk band. This suggests a moderate chance of returning within 30 days. Review discharge planning and follow-up.",
        "high": "High risk band. This suggests a high chance of returning within 30 days. Arrange early follow-up planning.",
    }[band]


def _guidance(scores: dict[str, float]) -> list[str]:
    bands = [_risk_band(scores[task]) for task in TASKS if task in scores]
    lines = [
        "- Confirm this estimate with the treating clinician and full record.",
        "- Review current observations and trajectory before escalation.",
    ]
    if "high" in bands:
        lines.append("- Consider earlier senior review given a high-band estimate.")
    else:
        lines.append("- Maintain routine monitoring and reassess if the condition changes.")
    lines.append("- Discuss discharge and 30-day follow-up if admission is nearing completion.")
    lines.append("- Seek urgent review for worsening breathing, chest pain, or reduced consciousness.")
    return lines[:5]


def _model_comparison(scores: dict[str, float]) -> str:
    pairs = [
        scores.get(f"{task}:{model}")
        for task in TASKS
        for model in ("AdaCare", "MCGRU", "RETAIN")
    ]
    if any(value is None for value in pairs):
        return "A complete three-model comparison is unavailable for this record."
    retain_highest = all(
        scores[f"{task}:RETAIN"] >= scores[f"{task}:{model}"]
        for task in TASKS
        for model in ("AdaCare", "MCGRU")
    )
    if retain_highest:
        return (
            "RETAIN gives the highest estimate on both tasks in this record. AdaCare is "
            "lowest for readmission; MCGRU sits between. Treat these differences as "
            "illustrative on the small demo test set."
        )
    return (
        "RETAIN is not uniformly highest in this record. The models differ modestly, so "
        "treat the comparison as illustrative on the small demo test set."
    )


def _local_answer(
    record_id: str,
    scores: dict[str, float],
    patient_line: str,
    references: list[Source],
) -> str:
    lines = ["Patient", patient_line, "", "Risk predictions"]
    lines.append("Task | AdaCare | MCGRU | RETAIN")
    for task, label in TASKS.items():
        cells = []
        for model in ("AdaCare", "MCGRU", "RETAIN"):
            key = f"{task}:{model}"
            cells.append(f"{scores[key]:.1%}" if key in scores else "unavailable")
        lines.append(f"{label} | {' | '.join(cells)}")

    lines.extend(["", "Risk explanation"])
    for task, label in (("outcome", "Mortality"), ("readmission", "Readmission")):
        if task in scores:
            lines.append(f"- {label}: {_band_sentence(task, _risk_band(scores[task]))}")
        else:
            lines.append(f"- {label}: Unavailable.")

    lines.extend(["", "Model comparison", _model_comparison(scores)])
    lines.extend(["", "Patient guidance"])
    lines.extend(_guidance(scores))

    lines.extend(["", "Clinical references"])
    if references:
        for index, source in enumerate(references[:3], start=1):
            suffix = f" — {source.url}" if source.url else ""
            lines.append(f"[{index}] {source.title}{suffix}")
    else:
        lines.append("No local references available.")

    mortality_band = _risk_band(scores["outcome"]) if "outcome" in scores else "unavailable"
    readmission_band = (
        _risk_band(scores["readmission"]) if "readmission" in scores else "unavailable"
    )
    lines.extend(
        [
            "",
            "Final summary",
            f"Overall, this demo record shows {mortality_band} mortality and "
            f"{readmission_band} readmission risk. RETAIN is the primary estimate. "
            "Use this as decision support, not a diagnosis.",
        ]
    )
    return "\n".join(lines)


class ClinicalAgent:
    name = "clinical_agent"

    def __init__(
        self,
        retriever: Retriever | None = None,
        llm: LLMService | None = None,
        prediction_dir: str | Path | None = None,
        records_path: str | Path | None = None,
        top_k: int | None = None,
    ) -> None:
        self.retriever = retriever if retriever is not None else Retriever()
        self.llm = llm if llm is not None else LLMService()
        self.prediction_dir = str(prediction_dir or PREDICTION_DIR)
        self.records_path = str(records_path or RECORDS_PATH)
        self.top_k = top_k or settings.retrieval_top_k

    def handles(self, intent: Intent) -> bool:
        return intent in (Intent.RECORD_QUERY, Intent.PREDICTION)

    def handle(
        self,
        request: ChatRequest,
        intent: Intent,
        history: Sequence[dict[str, str]] | None = None,
    ) -> AgentResult:
        if is_emergency(request.message):
            return AgentResult(
                answer=EMERGENCY_ANSWER,
                agent=self.name,
                intent=intent,
            )
        if not request.patient_id:
            return AgentResult(
                answer=(
                    "Provide a patient_id to look up a stored record and trained-model "
                    "risk scores. Use the RecordID from the processed EHR data."
                ),
                agent=self.name,
                intent=intent,
                status="not_available",
            )

        try:
            score_map = _load_predictions(self.prediction_dir)
            records = _load_records(self.records_path)
        except (OSError, ValueError):
            score_map, records = {}, None

        if not score_map:
            return AgentResult(
                answer="No trained-model predictions are available in this deployment.",
                agent=self.name,
                intent=intent,
                status="not_available",
            )

        known = {key for by_id in score_map.values() for key in by_id}
        record_id = _resolve_record_id(request.patient_id, records, known)
        if record_id is None:
            return AgentResult(
                answer=(
                    f"No trained-model prediction is available for patient_id "
                    f"'{request.patient_id}'. Use a RecordID from the processed EHR data."
                ),
                agent=self.name,
                intent=intent,
                status="not_available",
            )

        scores: dict[str, float] = {}
        for task in TASKS:
            if (task, "RETAIN") in score_map:
                scores[task] = score_map[(task, "RETAIN")][record_id]
            for model in MODELS:
                key = f"{task}:{model}"
                if (task, model) in score_map:
                    scores[key] = score_map[(task, model)][record_id]

        sources: list[Source] = []
        record_source = _record_source(records, record_id)
        if record_source is not None:
            sources.append(record_source)
        sources.extend(_model_sources_for_record(score_map, record_id))

        chunks = self._retrieve_references()
        references = self._to_reference_sources(chunks)
        sources.extend(references)

        answer = _local_answer(record_id, scores, _patient_line(records, record_id), references)
        if request.external_llm_consent:
            note = self._explain(scores, chunks)
            answer += f"\n\nPlain-language note\n{note}"

        return AgentResult(
            answer=answer,
            agent=self.name,
            intent=intent,
            sources=sources,
        )

    def _retrieve_references(self) -> list[RetrievedChunk]:
        try:
            return self.retriever.retrieve(RETRIEVAL_QUERY, k=3)
        except Exception:
            return []

    def _explain(
        self, scores: dict[str, float], chunks: list[RetrievedChunk]
    ) -> str:
        context = "\n\n".join(
            f"[{index}] {chunk.title}\n{chunk.text}"
            for index, chunk in enumerate(chunks, start=1)
        ) or "(no reference passages available)"
        bands = "\n".join(
            f"- {TASKS[task]}: {_risk_band(scores[task])}"
            for task in TASKS
            if task in scores
        )
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    f"Risk bands:\n{bands}\n\nReference passages:\n{context}\n\n"
                    "Explain the bands briefly. Do not repeat the table."
                ),
            },
        ]
        try:
            return self.llm.complete(messages)
        except LLMError:
            return "Live explanation was unavailable; the local scores above remain valid."

    @staticmethod
    def _to_reference_sources(chunks: list[RetrievedChunk]) -> list[Source]:
        sources: list[Source] = []
        seen: set[tuple[str, str]] = set()
        for chunk in chunks:
            key = (chunk.title, chunk.url)
            if key in seen:
                continue
            seen.add(key)
            sources.append(
                Source(
                    type=SourceType.REFERENCE,
                    title=chunk.title,
                    url=chunk.url,
                    snippet=_snippet(chunk.text),
                    score=chunk.score,
                )
            )
            if len(sources) == 3:
                break
        return sources


def _model_sources_for_record(
    score_map: dict[tuple[str, str], dict[str, float]], record_id: str
) -> list[Source]:
    sources: list[Source] = []
    for (task, model), by_id in score_map.items():
        if record_id not in by_id:
            continue
        score = by_id[record_id]
        sources.append(
            Source(
                type=SourceType.MODEL,
                title=f"{model} - {TASKS[task]}",
                snippet=f"Record {record_id}: {score:.1%} estimated risk.",
                score=score,
            )
        )
    return sources


def _snippet(text: str) -> str:
    snippet = text.strip().replace("\n", " ")
    return snippet[:220] + "…" if len(snippet) > 220 else snippet
