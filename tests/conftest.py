"""Shared test doubles. No test may call the network or require an API key."""

from __future__ import annotations

from collections.abc import Sequence

import pytest

from backend.llm.llm_service import LLMError, LLMService
from backend.rag.retriever import RetrievedChunk


class FakeLLM(LLMService):
    def __init__(
        self,
        response: str = "General guidance with a citation [1].",
        json_response: dict | None = None,
    ) -> None:
        super().__init__(api_key="test-key")
        self.response = response
        self.json_response = json_response or {"intent": "general_question"}
        self.calls: list[list[dict[str, str]]] = []

    def complete(
        self,
        messages: Sequence[dict[str, str]],
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> str:
        self.calls.append([dict(message) for message in messages])
        return self.response

    def complete_json(
        self,
        messages: Sequence[dict[str, str]],
        max_tokens: int | None = None,
    ) -> dict:
        self.calls.append([dict(message) for message in messages])
        return self.json_response


class FailingLLM(LLMService):
    def __init__(self) -> None:
        super().__init__(api_key="test-key")

    def complete(self, *args, **kwargs) -> str:
        raise LLMError("Groq is unavailable in tests.")

    def complete_json(self, *args, **kwargs) -> dict:
        raise LLMError("Groq is unavailable in tests.")


class FakeRetriever:
    def __init__(self, chunks: list[RetrievedChunk] | None = None) -> None:
        self.chunks = (
            chunks
            if chunks is not None
            else [
                RetrievedChunk(
                    text="Type 2 diabetes causes thirst, frequent urination, and tiredness.",
                    title="Type 2 diabetes: overview",
                    url="https://www.who.int/news-room/fact-sheets/detail/diabetes",
                    score=0.82,
                ),
                RetrievedChunk(
                    text="Diagnosis uses fasting glucose, HbA1c, or an oral glucose test.",
                    title="Type 2 diabetes: diagnosis",
                    url="https://www.who.int/news-room/fact-sheets/detail/diabetes",
                    score=0.61,
                ),
            ]
        )
        self.queries: list[str] = []

    def retrieve(self, query: str, k: int | None = None) -> list[RetrievedChunk]:
        self.queries.append(query)
        return self.chunks[: (k or len(self.chunks))]


@pytest.fixture
def fake_llm() -> FakeLLM:
    return FakeLLM()


@pytest.fixture
def fake_retriever() -> FakeRetriever:
    return FakeRetriever()
