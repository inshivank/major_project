"""Medical Report Agent, independent of clinical records and trained models."""

import time
from collections.abc import Sequence
from backend.agents.base import AgentResult
from backend.agents.patient_agent import is_emergency, EMERGENCY_ANSWER
from backend.config.settings import Settings, settings
from backend.reports.extraction import IsolatedExtractor
from backend.reports.explanation import ReportExplainer
from backend.reports.parser import parse
from backend.schemas.chat import ChatRequest, Intent
from backend.schemas.report import ReportMetadata, ReportResponse


class ReportAgent:
    name = "report_agent"  # Existing chat API agent identifier retained.

    def __init__(
        self, extractor=None, retriever=None, llm=None, config: Settings = settings
    ):
        self.config = config
        self.extractor = (
            extractor if extractor is not None else IsolatedExtractor(config)
        )
        self.explainer = ReportExplainer(retriever, llm, config)

    def handles(self, intent: Intent) -> bool:
        return intent is Intent.REPORT_EXPLANATION

    def handle(
        self,
        request: ChatRequest,
        intent: Intent,
        history: Sequence[dict[str, str]] | None = None,
    ) -> AgentResult:
        if is_emergency(request.message):
            return AgentResult(answer=EMERGENCY_ANSWER, agent=self.name, intent=intent)
        # No upload means no analysis. History is deliberately ignored and not sent externally.
        return AgentResult(
            answer="Upload the document to POST /reports/analyze. Set external_llm_consent=true only if you consent to sending canonical test names and comparison statuses to Groq. No report was analysed in this chat.",
            agent=self.name,
            intent=intent,
            status="not_available",
        )

    def analyze(self, data: bytes, consent: bool = False) -> ReportResponse:
        deadline = time.monotonic() + self.config.report_processing_timeout_seconds
        extraction = self.extractor.extract(data)
        tests, report_type, warnings = parse(extraction)
        warnings = [*extraction.warnings, *warnings]
        summary, sources, explanation_warnings, used = self.explainer.explain(
            tests, consent=consent, deadline=deadline
        )
        warnings.extend(explanation_warnings)
        partial = bool(
            extraction.warnings
            or not tests
            or any(t.uncertain or t.warnings for t in tests)
            or explanation_warnings
        )
        return ReportResponse(
            status="partial" if partial else "completed",
            report_type=report_type,
            metadata=ReportMetadata(
                page_count=extraction.page_count,
                extracted_pages=[s.page for s in extraction.segments],
            ),
            tests=tests,
            summary=summary,
            sources=sources,
            warnings=warnings,
            disclaimer=self.config.disclaimer,
            external_llm_used=used,
        )
