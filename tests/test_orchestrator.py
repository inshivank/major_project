from backend.agents.patient_agent import PatientAgent
from backend.agents.stubs import ClinicalAgent, ReportAgent
from backend.orchestrator.orchestrator import Orchestrator, merge_sources
from backend.orchestrator.router import Router
from backend.orchestrator.session_store import SessionStore
from backend.schemas.chat import ChatRequest, Intent, Source, SourceType
from tests.conftest import FakeLLM, FakeRetriever


def build_orchestrator():
    llm = FakeLLM()
    return Orchestrator(
        agents=[
            PatientAgent(retriever=FakeRetriever(), llm=llm),
            ReportAgent(),
            ClinicalAgent(),
        ],
        router=Router(llm=llm),
        store=SessionStore(max_sessions=5, max_turns=6),
        disclaimer="Test disclaimer.",
    )


def test_general_question_dispatches_to_patient_agent():
    orchestrator = build_orchestrator()
    response = orchestrator.chat(
        ChatRequest(message="What are the symptoms of type 2 diabetes?")
    )

    assert response.agent == "patient_agent"
    assert response.intent is Intent.GENERAL_QUESTION
    assert response.status == "ok"
    assert response.disclaimer == "Test disclaimer."
    assert response.session_id
    assert response.sources


def test_generated_session_id_is_reused_across_turns():
    orchestrator = build_orchestrator()
    first = orchestrator.chat(ChatRequest(message="What is asthma?"))
    second = orchestrator.chat(
        ChatRequest(message="What triggers it?", session_id=first.session_id)
    )

    assert second.session_id == first.session_id
    assert len(orchestrator.store.history(first.session_id)) == 4


def test_prediction_routes_to_stub_without_fabricating():
    response = build_orchestrator().chat(
        ChatRequest(message="What is the mortality risk for this patient?")
    )

    assert response.agent == "clinical_agent"
    assert response.intent is Intent.PREDICTION
    assert response.status == "not_available"
    assert "No prediction has been generated" in response.answer


def test_report_question_routes_to_report_stub():
    response = build_orchestrator().chat(
        ChatRequest(message="Explain this lab report")
    )

    assert response.agent == "report_agent"
    assert response.status == "not_available"


def test_merge_sources_keeps_best_score_and_dedupes():
    sources = [
        Source(title="A", url="u", score=0.2),
        Source(title="A", url="u", score=0.9),
        Source(title="B", url=None, score=0.5),
    ]

    merged = merge_sources(sources)

    assert len(merged) == 2
    assert merged[0].title == "A"
    assert merged[0].score == 0.9


def test_merge_sources_prefers_specific_type_of_duplicate():
    sources = [
        Source(type=SourceType.REFERENCE, title="X", url="u", score=0.4),
        Source(type=SourceType.REFERENCE, title="X", url="u", score=0.7),
    ]
    assert merge_sources(sources)[0].score == 0.7
