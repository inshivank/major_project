import pandas as pd
import pytest

from backend.agents.clinical_agent import ClinicalAgent
from backend.rag.retriever import RetrievedChunk
from backend.schemas.chat import ChatRequest, Intent, SourceType
from tests.conftest import FakeLLM, FailingLLM, FakeRetriever

RECORD_ID = "10000032_39553978"
PATIENT_ID = "10000032"


@pytest.fixture
def clinical_data(tmp_path):
    prediction_dir = tmp_path / "predictions"
    prediction_dir.mkdir()
    for task, model, score in (
        ("outcome", "retain", 0.72),
        ("readmission", "retain", 0.31),
        ("outcome", "adacare", 0.55),
        ("readmission", "adacare", 0.48),
        ("outcome", "mcgru", 0.61),
        ("readmission", "mcgru", 0.42),
    ):
        pd.to_pickle({RECORD_ID: score}, prediction_dir / f"mimic_{task}_{model}.pkl")

    records_path = tmp_path / "records.csv"
    pd.DataFrame(
        [
            {
                "RecordID": RECORD_ID,
                "PatientID": int(PATIENT_ID),
                "AdmissionID": 29079034,
                "RecordTime": "2180-07-23 14:00:00",
                "Age": 52,
                "Sex": "F",
                "Heart Rate": 92.0,
                "Oxygen saturation": 97.5,
            },
            {
                "RecordID": RECORD_ID,
                "PatientID": int(PATIENT_ID),
                "AdmissionID": 29079034,
                "RecordTime": "2180-07-23 15:00:00",
                "Age": 52,
                "Sex": "F",
                "Heart Rate": 94.0,
                "Oxygen saturation": 97.0,
            },
        ]
    ).to_csv(records_path, index=False)
    return prediction_dir, records_path


def make_agent(clinical_data, llm=None, retriever=None):
    prediction_dir, records_path = clinical_data
    return ClinicalAgent(
        llm=llm or FakeLLM(),
        retriever=retriever or FakeRetriever([]),
        prediction_dir=prediction_dir,
        records_path=records_path,
    )


def test_exact_record_id_returns_scores_and_sources(clinical_data):
    result = make_agent(clinical_data).handle(
        ChatRequest(message="Predict risk", patient_id=RECORD_ID),
        Intent.PREDICTION,
    )

    assert result.status == "ok"
    assert "72.0%" in result.answer
    assert "31.0%" in result.answer
    assert "| In-hospital mortality | 55.0% | 61.0% | 72.0% |" in result.answer
    assert "| 30-day readmission | 48.0% | 42.0% | 31.0% |" in result.answer
    assert any(source.type is SourceType.RECORD for source in result.sources)
    assert sum(source.type is SourceType.MODEL for source in result.sources) == 6


def test_patient_id_maps_to_stored_record(clinical_data):
    result = make_agent(clinical_data).handle(
        ChatRequest(message="Summarize this patient", patient_id=PATIENT_ID),
        Intent.RECORD_QUERY,
    )

    assert result.status == "ok"
    assert RECORD_ID in result.answer


def test_without_consent_llm_is_not_called(clinical_data):
    llm = FakeLLM()
    result = make_agent(clinical_data, llm=llm).handle(
        ChatRequest(message="Predict risk", patient_id=RECORD_ID),
        Intent.PREDICTION,
    )

    assert llm.calls == []
    assert not any(source.type is SourceType.REFERENCE for source in result.sources)


def test_consent_explains_without_sending_patient_values(clinical_data):
    llm = FakeLLM(response="General factors include severity of illness [1].")
    retriever = FakeRetriever(
        [
            RetrievedChunk(
                text="Illness severity and age are associated with outcomes.",
                title="Risk factors",
                url="https://example.org/risk",
                score=0.7,
            )
        ]
    )
    result = make_agent(clinical_data, llm=llm, retriever=retriever).handle(
        ChatRequest(
            message="Predict risk",
            patient_id=RECORD_ID,
            external_llm_consent=True,
        ),
        Intent.PREDICTION,
    )

    prompt = str(llm.calls[0])
    assert RECORD_ID not in prompt
    assert "Heart Rate" not in prompt
    assert "high" in prompt
    assert "General factors" in result.answer
    assert any(source.type is SourceType.REFERENCE for source in result.sources)


def test_unknown_patient_id_is_not_available(clinical_data):
    result = make_agent(clinical_data).handle(
        ChatRequest(message="Predict risk", patient_id="99999999_99999999"),
        Intent.PREDICTION,
    )

    assert result.status == "not_available"
    assert "No trained-model prediction" in result.answer


def test_llm_failure_falls_back_to_local_scores(clinical_data):
    result = make_agent(clinical_data, llm=FailingLLM()).handle(
        ChatRequest(
            message="Predict risk",
            patient_id=RECORD_ID,
            external_llm_consent=True,
        ),
        Intent.PREDICTION,
    )

    assert result.status == "ok"
    assert "72.0%" in result.answer
    assert "Live explanation was unavailable" in result.answer
