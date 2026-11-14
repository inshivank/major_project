from backend.agents.patient_agent import (
    EMERGENCY_ANSWER,
    PatientAgent,
    is_diagnosis_request,
    is_emergency,
)
from backend.schemas.chat import ChatRequest, Intent, SourceType
from tests.conftest import FakeLLM, FakeRetriever


def build_agent(llm=None, retriever=None):
    return PatientAgent(
        retriever=retriever or FakeRetriever(),
        llm=llm or FakeLLM(),
        top_k=2,
    )


def test_general_question_returns_grounded_answer_with_sources():
    llm = FakeLLM(response="Diabetes causes thirst and tiredness [1].")
    agent = build_agent(llm=llm)

    result = agent.handle(
        ChatRequest(message="What are the symptoms of type 2 diabetes?"),
        Intent.GENERAL_QUESTION,
    )

    assert result.status == "ok"
    assert result.intent is Intent.GENERAL_QUESTION
    assert "[1]" in result.answer
    assert result.sources
    assert result.sources[0].type is SourceType.REFERENCE
    assert result.sources[0].url.startswith("https://www.who.int")

    user_message = llm.calls[0][-1]["content"]
    assert "Context passages:" in user_message
    assert "[1] Type 2 diabetes: overview" in user_message


def test_sources_deduplicate_same_reference():
    retriever = FakeRetriever(
        chunks=[
            FakeRetriever().chunks[0],
            FakeRetriever().chunks[1],
        ]
    )
    agent = build_agent(retriever=retriever)
    result = agent.handle(ChatRequest(message="diabetes"), Intent.GENERAL_QUESTION)
    assert len(result.sources) == 1


def test_emergency_short_circuits_without_llm_call():
    llm = FakeLLM()
    agent = build_agent(llm=llm)

    result = agent.handle(
        ChatRequest(message="I have severe chest pain right now"),
        Intent.GENERAL_QUESTION,
    )

    assert result.answer == EMERGENCY_ANSWER
    assert "emergency" in result.answer.lower()
    assert llm.calls == []
    assert result.sources[0].title == "Emergency warning signs"


def test_diagnosis_request_gets_deterministic_refusal_prefix():
    agent = build_agent()
    result = agent.handle(
        ChatRequest(message="Do I have diabetes?"),
        Intent.GENERAL_QUESTION,
    )
    assert result.answer.startswith("I can't diagnose a condition")
    assert "Do not give one" in agent.llm.calls[0][-1]["content"]


def test_short_follow_up_reuses_previous_question_for_retrieval():
    retriever = FakeRetriever()
    agent = build_agent(retriever=retriever)
    history = [
        {"role": "user", "content": "Tell me about asthma"},
        {"role": "assistant", "content": "Asthma is a chronic airway condition."},
    ]

    agent.handle(
        ChatRequest(message="what symptoms?"),
        Intent.GENERAL_QUESTION,
        history,
    )

    assert retriever.queries == ["Tell me about asthma what symptoms?"]


def test_history_is_forwarded_to_llm():
    llm = FakeLLM()
    agent = build_agent(llm=llm)
    history = [
        {"role": "user", "content": "Tell me about asthma"},
        {"role": "assistant", "content": "Asthma is a chronic airway condition."},
    ]

    agent.handle(
        ChatRequest(message="What triggers an asthma attack?"),
        Intent.GENERAL_QUESTION,
        history,
    )

    roles = [message["role"] for message in llm.calls[0]]
    assert roles == ["system", "user", "assistant", "user"]


def test_guardrail_detectors():
    assert is_emergency("I cannot breathe properly")
    assert is_emergency("she has slurred speech")
    assert not is_emergency("What causes a sore throat?")
    assert is_diagnosis_request("Do I have cancer?")
    assert is_diagnosis_request("What dose should I take?")
    assert not is_diagnosis_request("What are the symptoms of flu?")
