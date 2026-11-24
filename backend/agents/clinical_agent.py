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
from backend.rag.retriever import Retriever, RetrievedChunk
from backend.schemas.chat import ChatRequest, Intent, Source, SourceType

PREDICTION_DIR = PROJECT_ROOT / "predictions"
RECORDS_PATH = PROJECT_ROOT / "data" / "processed" / "mimic_demo_formatted.csv"

TASKS = {
    "outcome": "In-hospital mortality",
    "readmission": "30-day readmission",
}
MODELS = ("RETAIN", "AdaCare", "MCGRU")

RETRIEVAL_QUERY = (
    "ICU in-hospital mortality and 30-day readmission risk factors patient education"
)

SYSTEM_PROMPT = (
    "You explain cached clinical model risk bands for a clinician. Use only the task "
    "names, risk bands, and numbered reference passages supplied. Do not diagnose, "
    "prescribe, invent patient details, or mention any identifier or record value. "
    "Cite passages as [1], [2]. Keep the answer under 150 words and add a safety caveat."
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


def _record_source(records: pd.DataFrame | None, record_id: str) -> Source | None:
    if records is None or records.empty or "RecordID" not in records.columns:
        return None
    rows = records.loc[records["RecordID"].astype(str) == record_id]
    if rows.empty:
        return None
    latest = rows.iloc[-1]
    fields: list[str] = []
    for column in (
        "Age",
        "Sex",
        "Heart Rate",
        "Oxygen saturation",
        "Systolic blood pressure",
        "Diastolic blood pressure",
        "Respiratory rate",
        "Temperature",
        "GCS total",
    ):
        if column in rows.columns and pd.notna(latest[column]):
            fields.append(f"{column}: {latest[column]}")
    detail = "; ".join(fields) if fields else "no numeric observations stored"
    snippet = f"{len(rows)} hourly records; latest {detail}."
    return Source(
        type=SourceType.RECORD,
        title=f"EHR record {record_id}",
        snippet=snippet[:300],
    )


def _local_answer(record_id: str, scores: dict[str, float]) -> str:
    lines = [
        f"Trained-model risk estimates for record {record_id} "
        "(MIMIC-IV demo, research use only)."
    ]
    for task, label in TASKS.items():
        if task in scores:
            score = scores[task]
            lines.append(
                f"- {label}: {score:.1%} ({_risk_band(score)} risk, RETAIN model)."
            )
    lines.append("")
    lines.append("| Task | AdaCare | MCGRU | RETAIN |")
    lines.append("|---|---:|---:|---:|")
    for task, label in TASKS.items():
        cells = []
        for model in ("AdaCare", "MCGRU", "RETAIN"):
            key = f"{task}:{model}"
            cells.append(f"{scores[key]:.1%}" if key in scores else "n/a")
        lines.append(f"| {label} | {' | '.join(cells)} |")
    lines.append("")
    lines.append(
        "These are research estimates, not a diagnosis. Confirm with a clinician "
        "and the full patient record before acting."
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

        answer = _local_answer(record_id, scores)
        sources: list[Source] = []
        record_source = _record_source(records, record_id)
        if record_source is not None:
            sources.append(record_source)
        sources.extend(_model_sources_for_record(score_map, record_id))

        if request.external_llm_consent:
            explanation, references = self._explain(scores)
            if explanation:
                answer += f"\n\nExplanation:\n{explanation}"
            sources.extend(references)

        return AgentResult(
            answer=answer,
            agent=self.name,
            intent=intent,
            sources=sources,
        )

    def _explain(
        self, scores: dict[str, float]
    ) -> tuple[str, list[Source]]:
        chunks: list[RetrievedChunk] = []
        try:
            chunks = self.retriever.retrieve(RETRIEVAL_QUERY, k=self.top_k)
        except Exception:
            chunks = []

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
                    "Explain what the bands mean in general terms."
                ),
            },
        ]
        try:
            explanation = self.llm.complete(messages)
        except LLMError:
            return "Live explanation was unavailable; local model scores are shown above.", []

        references = [
            Source(
                type=SourceType.REFERENCE,
                title=chunk.title,
                url=chunk.url,
                snippet=_snippet(chunk.text),
                score=chunk.score,
            )
            for chunk in chunks
        ]
        return explanation, references


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
