"""Intent routing: deterministic rules first, LLM classification as fallback."""

from __future__ import annotations

import logging
import re

from backend.llm.llm_service import LLMError, LLMService
from backend.schemas.chat import Intent
from backend.reports.parser import LABELS

logger = logging.getLogger(__name__)

LAB_MEASUREMENT_PATTERN = re.compile(
    r"\b(?:"
    + "|".join(re.escape(alias) for alias, _ in LABELS)
    + r")[\s:|]+(?:[<>\u2264\u2265]=?\s*)?[+-]?(?:\d+(?:\.\d+)?|\.\d+)\b",
    re.IGNORECASE,
)

REPORT_PATTERNS = (
    LAB_MEASUREMENT_PATTERN,
    re.compile(
        r"\b(lab|blood|urine|pathology) (result|test|report)s?\b", re.IGNORECASE
    ),
    re.compile(r"\b(report|scan|x-?ray|mri|ct scan|ecg|ekg)\b", re.IGNORECASE),
    re.compile(r"\bexplain (this|the|my) (report|result|scan)\b", re.IGNORECASE),
    re.compile(r"\b(upload|attach) (a |the )?(report|scan|document)\b", re.IGNORECASE),
)

PREDICTION_PATTERNS = (
    re.compile(r"\b(predict|prediction|prognosis)\b", re.IGNORECASE),
    re.compile(r"\brisk of (death|dying|mortality|readmission)\b", re.IGNORECASE),
    re.compile(
        r"\b(mortality|readmission|survival) (risk|probability|chance)\b", re.IGNORECASE
    ),
    re.compile(
        r"\b(will (he|she|they|the patient) (die|survive|be readmitted))\b",
        re.IGNORECASE,
    ),
)

RECORD_PATTERNS = (
    re.compile(r"\b(this patient|the patient|patient'?s?)\b", re.IGNORECASE),
    re.compile(
        r"\b(his|her|their)\b[^.?!]*\b(history|record|chart|medications?)\b",
        re.IGNORECASE,
    ),
    re.compile(r"\b(current|active|list of) medications?\b", re.IGNORECASE),
    re.compile(r"\b(medical|clinical) (history|record|chart)\b", re.IGNORECASE),
    re.compile(r"\bsummari[sz]e (the|this) patient\b", re.IGNORECASE),
    re.compile(r"\bpatient_id\b", re.IGNORECASE),
)

INTENT_DESCRIPTIONS = (
    "general_question: general medical knowledge or patient education, not about a "
    "specific patient's stored data.\n"
    "record_query: asks for information stored in a specific patient's record "
    "(history, medications, notes, demographics).\n"
    "report_explanation: asks to interpret or explain a report, lab result, scan, or "
    "uploaded document.\n"
    "prediction: asks for a risk estimate such as mortality or readmission."
)


class Router:
    def __init__(self, llm: LLMService | None = None) -> None:
        self.llm = llm

    def route(self, message: str) -> Intent:
        intent = self._route_by_rules(message)
        if intent is not None:
            return intent
        if self.llm is not None and self.llm.available:
            return self._route_with_llm(message)
        return Intent.GENERAL_QUESTION

    @staticmethod
    def _route_by_rules(message: str) -> Intent | None:
        for pattern in REPORT_PATTERNS:
            if pattern.search(message):
                return Intent.REPORT_EXPLANATION
        for pattern in PREDICTION_PATTERNS:
            if pattern.search(message):
                return Intent.PREDICTION
        for pattern in RECORD_PATTERNS:
            if pattern.search(message):
                return Intent.RECORD_QUERY
        return None

    def _route_with_llm(self, message: str) -> Intent:
        prompt = (
            "Classify the user message into exactly one intent.\n"
            f"{INTENT_DESCRIPTIONS}\n"
            'Reply with JSON: {"intent": "<one of the four names>"}'
        )
        try:
            payload = self.llm.complete_json(
                [
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": message},
                ],
                max_tokens=40,
            )
            raw = str(payload.get("intent", "")).strip().lower()
            return Intent(raw)
        except (LLMError, ValueError):
            logger.info("Intent LLM classification failed; defaulting to general.")
            return Intent.GENERAL_QUESTION
