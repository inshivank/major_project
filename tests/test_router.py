import pytest

from backend.orchestrator.router import Router
from backend.schemas.chat import Intent
from tests.conftest import FakeLLM, FailingLLM


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("What are the symptoms of type 2 diabetes?", Intent.GENERAL_QUESTION),
        ("Summarize this patient's history", Intent.RECORD_QUERY),
        ("What are his current medications?", Intent.RECORD_QUERY),
        ("What is the risk of readmission for the patient?", Intent.PREDICTION),
        ("Predict the mortality risk", Intent.PREDICTION),
        ("Explain this lab report", Intent.REPORT_EXPLANATION),
        ("Can you explain my blood test results?", Intent.REPORT_EXPLANATION),
    ],
)
def test_rules_route_to_expected_intent(message, expected):
    assert Router().route(message) is expected


def test_llm_fallback_used_when_rules_do_not_match():
    llm = FakeLLM(json_response={"intent": "prediction"})
    assert Router(llm=llm).route("hello there") is Intent.PREDICTION
    assert llm.calls


def test_llm_fallback_failure_defaults_to_general():
    assert Router(llm=FailingLLM()).route("hello there") is Intent.GENERAL_QUESTION


def test_llm_fallback_invalid_label_defaults_to_general():
    llm = FakeLLM(json_response={"intent": "not_an_intent"})
    assert Router(llm=llm).route("hello there") is Intent.GENERAL_QUESTION
