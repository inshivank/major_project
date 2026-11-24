"""Regression checks use the real Groq SDK with an offline HTTP transport."""

import json
import time

import httpx
import pytest
from groq import Groq as RealGroq

from backend.llm.llm_service import LLMError, LLMService
from backend.reports.explanation import ReportExplainer
from backend.rag.retriever import RetrievedChunk
from backend.schemas.report import Measurement
from tests.conftest import FakeRetriever

QUOTE = "Hemoglobin carries oxygen in the blood."
SELECTION = {"excerpts": [{"source": 2, "quote": QUOTE}], "question_ids": [0]}


def completion(content=None, finish_reason="stop"):
    return {
        "id": "synthetic",
        "object": "chat.completion",
        "created": 0,
        "model": "synthetic-model",
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": json.dumps(SELECTION) if content is None else content,
                },
                "finish_reason": finish_reason,
            }
        ],
    }


def install_transport(monkeypatch, handler):
    def client_factory(**kwargs):
        return RealGroq(
            **kwargs, http_client=httpx.Client(transport=httpx.MockTransport(handler))
        )

    monkeypatch.setattr("backend.llm.llm_service.Groq", client_factory)


@pytest.mark.parametrize(
    "base,path",
    [
        ("https://api.groq.com", "/openai/v1/chat/completions"),
        ("https://api.groq.com/openai/v1", "/openai/v1/chat/completions"),
        ("https://api.groq.com/openai/v1/", "/openai/v1/chat/completions"),
        ("https://proxy.invalid/groq/openai/v1", "/groq/openai/v1/chat/completions"),
    ],
)
def test_real_sdk_adds_api_prefix_exactly_once(monkeypatch, base, path):
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json=completion())

    install_transport(monkeypatch, handler)
    service = LLMService(
        api_key="synthetic-key", base_url=base, model="openai/gpt-oss-20b"
    )
    assert (
        service.complete_json([{"role": "user", "content": "Synthetic task"}])
        == SELECTION
    )
    assert len(requests) == 1 and requests[0].url.path == path
    body = json.loads(requests[0].content)
    assert body["reasoning_effort"] == "low" and body["include_reasoning"] is False
    assert body["max_tokens"] == service.max_tokens


@pytest.mark.parametrize(
    "status,code",
    [
        (401, "llm_authentication"),
        (400, "llm_bad_request"),
        (404, "llm_not_found"),
        (403, "llm_api_error"),
    ],
)
def test_provider_errors_are_typed_sanitized_and_not_retried(monkeypatch, status, code):
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(
            status,
            json={
                "error": {
                    "message": "SENSITIVE VENDOR CONTENT",
                    "type": "invalid_request_error",
                    "code": "unknown_url",
                }
            },
        )

    install_transport(monkeypatch, handler)
    service = LLMService(
        api_key="synthetic-key", base_url="https://api.groq.com", max_retries=3
    )
    with pytest.raises(LLMError) as error:
        service.complete([{"role": "user", "content": "Synthetic task"}])
    assert error.value.code == code and error.value.status_code == status
    assert len(requests) == 1
    assert "SENSITIVE" not in str(error.value) and "synthetic-key" not in str(
        error.value
    )


def test_truncated_reasoning_completion_is_explicit_error(monkeypatch):
    def handler(request):
        return httpx.Response(200, json=completion(content="", finish_reason="length"))

    install_transport(monkeypatch, handler)
    with pytest.raises(LLMError) as error:
        LLMService(api_key="synthetic-key").complete_json(
            [{"role": "user", "content": "Synthetic task"}]
        )
    assert error.value.code == "llm_token_limit"


def test_real_sdk_grounded_citations_with_legacy_url(monkeypatch):
    requests = []

    def handler(request):
        requests.append(request)
        body = json.loads(request.content)
        assert "Numeric IDs are required" in body["messages"][0]["content"]
        evidence = json.loads(body["messages"][-1]["content"])["evidence"]
        assert evidence == [{"source": 2, "text": QUOTE, "allowed_quotes": [QUOTE]}]
        return httpx.Response(200, json=completion())

    install_transport(monkeypatch, handler)
    service = LLMService(
        api_key="synthetic-key", base_url="https://api.groq.com/openai/v1"
    )
    retriever = FakeRetriever(
        [
            RetrievedChunk(
                text=QUOTE,
                title="Synthetic reference",
                url="https://example.org/cbc",
                score=0.9,
            )
        ]
    )
    test = Measurement(
        name="Hemoglobin",
        original_label="Hb",
        value="10.2",
        unit="g/dL",
        reference_range="12-16",
        source_page=1,
    )
    summary, sources, warnings, used = ReportExplainer(retriever, service).explain(
        [test], consent=True, deadline=time.monotonic() + 20
    )
    assert used and not warnings
    assert QUOTE + " [2]" in summary
    assert [source.type.value for source in sources] == ["record", "reference"]
    assert sources[1].snippet == QUOTE and sources[1].url == "https://example.org/cbc"
    assert len(requests) == 1


def test_api_404_is_not_misreported_as_retrieval_failure(monkeypatch):
    def handler(request):
        return httpx.Response(
            404,
            json={
                "error": {
                    "message": "SENSITIVE VENDOR CONTENT",
                    "type": "invalid_request_error",
                    "code": "model_not_found",
                }
            },
        )

    install_transport(monkeypatch, handler)
    service = LLMService(api_key="synthetic-key", base_url="https://api.groq.com")
    retriever = FakeRetriever(
        [
            RetrievedChunk(
                text=QUOTE,
                title="Synthetic reference",
                url="https://example.org/cbc",
                score=0.9,
            )
        ]
    )
    test = Measurement(
        name="Hemoglobin", original_label="Hb", value="10.2", unit="g/dL", source_page=1
    )
    summary, sources, warnings, used = ReportExplainer(retriever, service).explain(
        [test], consent=True
    )
    assert used
    assert any("llm_not_found" in warning for warning in warnings)
    assert not any("retrieval unavailable" in warning.lower() for warning in warnings)
    assert len(sources) == 1 and sources[0].type.value == "record"
    assert "SENSITIVE" not in str(warnings)
