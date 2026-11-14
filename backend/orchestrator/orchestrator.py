"""Orchestrator: route a request to an agent and assemble the response."""

from __future__ import annotations

import logging
import uuid
from collections.abc import Sequence

from backend.agents.base import Agent, AgentResult
from backend.agents.patient_agent import PatientAgent
from backend.agents.stubs import ClinicalAgent, ReportAgent
from backend.config.settings import settings
from backend.llm.llm_service import LLMService
from backend.orchestrator.router import Router
from backend.orchestrator.session_store import SessionStore
from backend.rag.retriever import Retriever
from backend.schemas.chat import ChatRequest, ChatResponse, Intent, Source

logger = logging.getLogger(__name__)


class Orchestrator:
    def __init__(
        self,
        agents: Sequence[Agent],
        router: Router | None = None,
        store: SessionStore | None = None,
        disclaimer: str | None = None,
    ) -> None:
        self.agents = list(agents)
        self.router = router or Router()
        self.store = store or SessionStore()
        self.disclaimer = disclaimer or settings.disclaimer

    @classmethod
    def build_default(cls) -> "Orchestrator":
        """Wire the real Groq client, Chroma retriever, and agent registry."""
        llm = LLMService()
        retriever = Retriever()
        return cls(
            agents=[
                PatientAgent(retriever=retriever, llm=llm),
                ReportAgent(retriever=retriever, llm=llm),
                ClinicalAgent(),
            ],
            router=Router(llm=llm),
        )

    def chat(self, request: ChatRequest) -> ChatResponse:
        session_id = request.session_id or uuid.uuid4().hex
        history = self.store.history(session_id)
        intent = self.router.route(request.message)

        agent = self._select_agent(intent)
        result = agent.handle(request, intent, history)

        if intent is Intent.REPORT_EXPLANATION:
            # Never retain pasted report text or medical identifiers in report chat turns.
            self.store.add_turn(
                session_id,
                "[Report upload guidance requested]",
                "[Use /reports/analyze]",
            )
        else:
            self.store.add_turn(session_id, request.message, result.answer)

        return ChatResponse(
            answer=result.answer,
            sources=merge_sources(result.sources),
            agent=result.agent,
            intent=result.intent,
            status=result.status,
            session_id=session_id,
            disclaimer=self.disclaimer,
        )

    def _select_agent(self, intent: Intent) -> Agent:
        for agent in self.agents:
            if agent.handles(intent):
                return agent
        logger.warning("No agent registered for %s; using first agent.", intent)
        return self.agents[0]


def merge_sources(sources: Sequence[Source]) -> list[Source]:
    """Deduplicate sources, keeping the highest-scoring copy of each reference."""
    merged: dict[tuple[str, str], Source] = {}
    for source in sources:
        key = ("url", source.url) if source.url else ("title", source.title)
        existing = merged.get(key)
        if existing is None or (source.score or 0) > (existing.score or 0):
            merged[key] = source
    return sorted(
        merged.values(),
        key=lambda item: item.score or 0.0,
        reverse=True,
    )
