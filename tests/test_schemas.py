import pytest
from pydantic import ValidationError

from backend.schemas.chat import ChatRequest, ChatResponse, Intent, Source, SourceType


def test_chat_request_requires_message():
    with pytest.raises(ValidationError):
        ChatRequest(message="")


def test_chat_request_optional_fields_default_to_none():
    request = ChatRequest(message="hello")
    assert request.session_id is None
    assert request.patient_id is None
    assert request.external_llm_consent is False


def test_chat_request_rejects_overlong_message():
    with pytest.raises(ValidationError):
        ChatRequest(message="x" * 4001)


def test_chat_response_defaults():
    response = ChatResponse(
        answer="ok",
        agent="patient_agent",
        intent=Intent.GENERAL_QUESTION,
        session_id="abc",
    )
    assert response.sources == []
    assert response.status == "ok"
    assert response.disclaimer == ""


def test_source_defaults_to_reference():
    source = Source(title="Asthma")
    assert source.type is SourceType.REFERENCE
    assert source.url is None
