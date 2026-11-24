"""Request/response contracts for the chat API."""

from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


class Intent(str, Enum):
    GENERAL_QUESTION = "general_question"
    RECORD_QUERY = "record_query"
    REPORT_EXPLANATION = "report_explanation"
    PREDICTION = "prediction"


class SourceType(str, Enum):
    REFERENCE = "reference"
    RECORD = "record"
    MODEL = "model"


class Source(BaseModel):
    type: SourceType = SourceType.REFERENCE
    title: str
    url: str | None = None
    snippet: str | None = None
    score: float | None = None


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    session_id: str | None = None
    patient_id: str | None = None
    external_llm_consent: bool = False


class ChatResponse(BaseModel):
    answer: str
    sources: list[Source] = Field(default_factory=list)
    agent: str
    intent: Intent
    status: Literal["ok", "not_available"] = "ok"
    session_id: str
    disclaimer: str = ""
