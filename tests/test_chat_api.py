import pytest
from fastapi.testclient import TestClient

from backend.agents.clinical_agent import ClinicalAgent
from backend.agents.patient_agent import PatientAgent
from backend.agents.report_agent import ReportAgent
from backend.llm.llm_service import LLMError, LLMService
from backend.main import app, get_orchestrator
from backend.orchestrator.orchestrator import Orchestrator
from backend.orchestrator.router import Router
from tests.conftest import FakeLLM, FakeRetriever

client = TestClient(app)


class RaisingLLM(LLMService):
    def __init__(self) -> None:
        super().__init__(api_key="test-key")

    def complete(self, *args, **kwargs) -> str:
        raise LLMError("Groq is unavailable.")


def make_orchestrator(llm=None):
    llm = llm or FakeLLM()
    return Orchestrator(
        agents=[
            PatientAgent(retriever=FakeRetriever(), llm=llm),
            ReportAgent(),
            ClinicalAgent(),
        ],
        router=Router(llm=llm),
    )


@pytest.fixture(autouse=True)
def override_orchestrator():
    app.dependency_overrides[get_orchestrator] = lambda: make_orchestrator()
    yield
    app.dependency_overrides.clear()


def test_chat_endpoint_returns_structured_response():
    response = client.post("/chat", json={"message": "What is asthma?"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["agent"] == "patient_agent"
    assert payload["intent"] == "general_question"
    assert payload["session_id"]
    assert payload["disclaimer"]
    assert payload["sources"]


def test_demo_page_is_served():
    response = client.get("/demo")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "Find a patient record" in response.text


def test_chat_endpoint_rejects_empty_message():
    response = client.post("/chat", json={"message": ""})
    assert response.status_code == 422


def test_chat_endpoint_returns_503_when_llm_fails():
    app.dependency_overrides[get_orchestrator] = lambda: make_orchestrator(
        llm=RaisingLLM()
    )

    response = client.post("/chat", json={"message": "What is asthma?"})

    assert response.status_code == 503
    assert "unavailable" in response.json()["detail"].lower()


def test_prediction_request_is_not_available_but_not_an_error():
    response = client.post(
        "/chat", json={"message": "Predict readmission risk for this patient"}
    )

    assert response.status_code == 200
    assert response.json()["status"] == "not_available"
