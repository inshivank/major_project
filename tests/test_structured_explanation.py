"""Structured presentation never trusts model-generated measurements or citations."""

import pytest
from backend.agents.report_agent import ReportAgent
from backend.schemas.report import Extraction, Segment, StructuredExplanation
from backend.reports.explanation import ReportExplainer
from backend.reports.parser import parse
from tests.conftest import FakeRetriever, FailingLLM
from tests.test_reports import SelectionLLM, explainer, extraction, measurement, pdf


def test_additive_local_explanation_preserves_authoritative_data():
    report = ReportAgent().analyze(pdf())
    assert report.explanation.mode == "local"
    assert [t.parameter_id for t in report.tests] == [
        "parameter-1",
        "parameter-2",
        "parameter-3",
    ]
    assert [e.parameter_id for e in report.explanation.parameter_explanations] == [
        t.parameter_id for t in report.tests
    ]
    assert report.tests[0].value == "10.2" and report.tests[0].status == "below_range"
    assert "10.2" not in report.explanation.overall_summary
    assert report.summary and report.disclaimer == report.explanation.medical_disclaimer
    assert not report.external_llm_used


def test_validated_quote_is_associated_and_citations_exist():
    result = explainer().explain([measurement()], consent=True)
    explanation = result.explanation
    assert explanation.mode == "llm_assisted"
    assert explanation.parameter_explanations[0].what_it_measures[0].citation_ids == [2]
    assert (
        explanation.parameter_explanations[0].what_it_measures[0].text
        == "Hemoglobin carries oxygen in the blood."
    )
    assert explanation.parameter_explanations[0].citation_ids == [1]
    assert explanation.doctor_discussion_questions == [
        "Do any of these results need repeat testing?"
    ]
    StructuredExplanation.model_validate(explanation.model_dump())


@pytest.mark.parametrize(
    "payload",
    [
        {
            "excerpts": [
                {"source": 999, "quote": "Hemoglobin carries oxygen in the blood."}
            ],
            "question_ids": [],
        },
        {
            "excerpts": [
                {"source": 2, "quote": "You have disease and need medication."}
            ],
            "question_ids": [],
        },
        {"invented": "measurement"},
    ],
)
def test_invalid_model_output_cannot_enter_structured_explanation(payload):
    result = explainer(SelectionLLM(payload)).explain([measurement()], True)
    assert result.explanation.mode == "fallback"
    assert not result.explanation.parameter_explanations[0].what_it_measures
    assert result.explanation.citation_ids == [1]
    assert not result.explanation.educational_context


def test_provider_failure_uses_same_schema_and_local_status():
    result = explainer(FailingLLM()).explain([measurement()], True)
    assert result.explanation.mode == "fallback"
    assert result.warnings
    assert result.explanation.parameter_explanations[0].range_explanation.startswith(
        "This result cannot be compared safely"
    )


def test_no_consent_does_not_invoke_external_dependencies():
    class Forbidden:
        @property
        def available(self):
            raise AssertionError("External dependency touched")

        def retrieve(self, *a, **k):
            raise AssertionError("External dependency touched")

    result = ReportExplainer(Forbidden(), Forbidden()).explain([measurement()], False)
    assert result.explanation.mode == "local" and not result.used
    assert not result.explanation.parameter_explanations[0].what_it_measures


def test_duplicate_parameters_have_distinct_ids_and_missing_ranges_remain_unknown():
    tests, _, _ = parse(extraction("Hb 10 g/dL\nHb pending g/dL 12-16"))
    result = ReportExplainer().explain(tests)
    assert [p.parameter_id for p in result.explanation.parameter_explanations] == [
        "parameter-1",
        "parameter-2",
    ]
    assert all(t.status == "indeterminate" for t in tests)
    assert all(
        "cannot be compared safely" in p.range_explanation
        for p in result.explanation.parameter_explanations
    )
