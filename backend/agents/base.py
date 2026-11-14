"""Shared agent contracts."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Literal, Protocol

from backend.schemas.chat import ChatRequest, Intent, Source

AgentStatus = Literal["ok", "not_available"]


@dataclass
class AgentResult:
    answer: str
    agent: str
    intent: Intent
    sources: list[Source] = field(default_factory=list)
    status: AgentStatus = "ok"


class Agent(Protocol):
    name: str

    def handles(self, intent: Intent) -> bool: ...

    def handle(
        self,
        request: ChatRequest,
        intent: Intent,
        history: Sequence[dict[str, str]] | None = None,
    ) -> AgentResult: ...
