"""Patient Assistance agent: Groq + retrieval over the medical corpus."""

from __future__ import annotations

import re
from collections.abc import Sequence
from pathlib import Path

from backend.agents.base import AgentResult
from backend.config.settings import settings
from backend.llm.llm_service import LLMService
from backend.rag.retriever import Retriever, RetrievedChunk
from backend.schemas.chat import ChatRequest, Intent, Source, SourceType

PROMPT_PATH = Path(__file__).with_name("prompts") / "patient_agent.md"

EMERGENCY_PATTERNS = (
    re.compile(r"\bchest (pain|pressure|tightness)\b", re.IGNORECASE),
    re.compile(
        r"\b(can'?t|cannot|difficulty|trouble|hard to) breath\w*\b", re.IGNORECASE
    ),
    re.compile(r"\b(severe|heavy|uncontrolled) bleeding\b", re.IGNORECASE),
    re.compile(
        r"\b(suicid\w*|kill myself|end my life|harm myself|self[- ]harm)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(face (is )?drooping|slurred speech|numb\w* on one side|"
        r"weak\w* on one side|sudden vision loss)\b",
        re.IGNORECASE,
    ),
    re.compile(r"\b(unconscious|passed out|not breathing|overdose)\b", re.IGNORECASE),
    re.compile(r"\b(anaphylaxis|throat (is )?(closing|swelling))\b", re.IGNORECASE),
    re.compile(r"\b(seizure|convulsion)\b", re.IGNORECASE),
)

DIAGNOSIS_PATTERNS = (
    re.compile(r"\bdo i have\b", re.IGNORECASE),
    re.compile(r"\bwhat (disease|condition|illness) do i have\b", re.IGNORECASE),
    re.compile(r"\bdiagnose me\b|\bdo i have (cancer|diabetes|a stroke)\b", re.IGNORECASE),
    re.compile(r"\bwhat('s| is) wrong with me\b", re.IGNORECASE),
    re.compile(r"\bprescribe\b|\bwhat (dose|dosage) should i take\b", re.IGNORECASE),
    re.compile(r"\bis it (cancer|serious|dangerous)\b", re.IGNORECASE),
)

EMERGENCY_ANSWER = (
    "This may be a medical emergency. Call your local emergency number now "
    "(for example 911, 112, or 108 depending on your country) or go to the nearest "
    "emergency department. Do not wait for an online answer. If you are with "
    "someone who is unwell, stay with them, keep them as comfortable and safe as "
    "possible, and follow the dispatcher's instructions."
)

DIAGNOSIS_PREFIX = (
    "I can't diagnose a condition or prescribe a medicine. Only a clinician who can "
    "examine you and review your tests can do that. I can share general information "
    "to help you prepare for that conversation.\n\n"
)

def is_emergency(text: str) -> bool:
    return any(pattern.search(text) for pattern in EMERGENCY_PATTERNS)


def is_diagnosis_request(text: str) -> bool:
    return any(pattern.search(text) for pattern in DIAGNOSIS_PATTERNS)


class PatientAgent:
    name = "patient_agent"

    def __init__(
        self,
        retriever: Retriever,
        llm: LLMService | None = None,
        top_k: int | None = None,
    ) -> None:
        self.retriever = retriever
        self.llm = llm or LLMService()
        self.top_k = top_k or settings.retrieval_top_k
        self.system_prompt = PROMPT_PATH.read_text(encoding="utf-8").strip()

    def handles(self, intent: Intent) -> bool:
        return intent is Intent.GENERAL_QUESTION

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
                sources=[
                    Source(
                        type=SourceType.REFERENCE,
                        title="Emergency warning signs",
                        url="https://www.nhs.uk/nhs-services/urgent-and-emergency-care-services/when-to-call-999/",
                    )
                ],
            )

        chunks = self.retriever.retrieve(
            self._build_query(request.message, history), k=self.top_k
        )
        messages = self._build_messages(request.message, chunks, history or [])
        answer = self.llm.complete(messages)

        if is_diagnosis_request(request.message):
            answer = DIAGNOSIS_PREFIX + answer

        return AgentResult(
            answer=answer,
            agent=self.name,
            intent=intent,
            sources=self._to_sources(chunks),
        )

    def _build_query(
        self, message: str, history: Sequence[dict[str, str]] | None
    ) -> str:
        """Short follow-ups lose context, so prepend the previous user turn."""
        if not history:
            return message
        if len(message.split()) >= 6:
            return message
        previous = next(
            (
                turn["content"]
                for turn in reversed(history)
                if turn.get("role") == "user" and turn.get("content")
            ),
            None,
        )
        return f"{previous} {message}" if previous else message

    def _build_messages(
        self,
        message: str,
        chunks: Sequence[RetrievedChunk],
        history: Sequence[dict[str, str]],
    ) -> list[dict[str, str]]:
        messages: list[dict[str, str]] = [
            {"role": "system", "content": self.system_prompt}
        ]
        messages.extend(
            {"role": turn["role"], "content": turn["content"]}
            for turn in history
            if turn.get("role") in {"user", "assistant"} and turn.get("content")
        )

        context = self._format_context(chunks)
        instruction = ""
        if is_diagnosis_request(message):
            instruction = (
                "\n\nThe user is asking for a diagnosis or a prescription. Do not "
                "give one. Explain that only a clinician can diagnose or prescribe, "
                "then offer general education and suggest an appropriate consultation."
            )

        messages.append(
            {
                "role": "user",
                "content": (
                    f"Context passages:\n{context}\n\n"
                    f"Question: {message}{instruction}"
                ),
            }
        )
        return messages

    @staticmethod
    def _format_context(chunks: Sequence[RetrievedChunk]) -> str:
        if not chunks:
            return "(no relevant passages were found)"

        lines: list[str] = []
        for index, chunk in enumerate(chunks, start=1):
            source = f" — {chunk.url}" if chunk.url else ""
            lines.append(f"[{index}] {chunk.title}{source}\n{chunk.text}")
        return "\n\n".join(lines)

    @staticmethod
    def _to_sources(chunks: Sequence[RetrievedChunk]) -> list[Source]:
        sources: list[Source] = []
        seen: set[tuple[str, str]] = set()
        for chunk in chunks:
            key = ("url", chunk.url) if chunk.url else ("title", chunk.title)
            if key in seen:
                continue
            seen.add(key)
            snippet = chunk.text.strip().replace("\n", " ")
            sources.append(
                Source(
                    type=SourceType.REFERENCE,
                    title=chunk.title,
                    url=chunk.url,
                    snippet=(snippet[:220] + "…") if len(snippet) > 220 else snippet,
                    score=chunk.score,
                )
            )
        return sources
