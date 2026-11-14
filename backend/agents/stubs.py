"""Placeholder agents for capabilities scheduled in later weeks.

They return an explicit ``not_available`` status so the UI can distinguish an
unimplemented feature from a real answer. They never fabricate records or predictions.
"""

from __future__ import annotations

from collections.abc import Sequence

from backend.agents.base import AgentResult
from backend.schemas.chat import ChatRequest, Intent


class ClinicalAgent:
    """Record retrieval and model-based predictions (Weeks 3+)."""

    name = "clinical_agent"

    _MESSAGES = {
        Intent.RECORD_QUERY: (
            "Patient-record questions are not available yet. EHR integration and "
            "record retrieval are planned for a later week, so I cannot read this "
            "patient's history, results, or notes right now."
        ),
        Intent.PREDICTION: (
            "Prediction is not available yet. The trained decision models (AdaCare, "
            "MCGRU, RETAIN) are planned for a later week, so I cannot estimate "
            "mortality or readmission risk yet. No prediction has been generated."
        ),
    }

    def handles(self, intent: Intent) -> bool:
        return intent in self._MESSAGES

    def handle(
        self,
        request: ChatRequest,
        intent: Intent,
        history: Sequence[dict[str, str]] | None = None,
    ) -> AgentResult:
        return AgentResult(
            answer=self._MESSAGES.get(
                intent, "This capability is not available yet."
            ),
            agent=self.name,
            intent=intent,
            status="not_available",
        )


class ReportAgent:
    """Medical report understanding with OCR (Weeks 4+)."""

    name = "report_agent"

    def handles(self, intent: Intent) -> bool:
        return intent is Intent.REPORT_EXPLANATION

    def handle(
        self,
        request: ChatRequest,
        intent: Intent,
        history: Sequence[dict[str, str]] | None = None,
    ) -> AgentResult:
        return AgentResult(
            answer=(
                "Report understanding is not available yet. Document upload, OCR, "
                "and lab-result explanation are planned for a later week. No report "
                "was analysed."
            ),
            agent=self.name,
            intent=intent,
            status="not_available",
        )
