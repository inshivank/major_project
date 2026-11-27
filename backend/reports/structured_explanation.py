"""Presentation structure assembled only from authoritative results and validated quotes."""

import re
from backend.reports.parser import ALIASES
from backend.schemas.report import (
    CitedExplanation,
    ParameterExplanation,
    StructuredExplanation,
)

LIMITATIONS = [
    "Values outside a stated range do not necessarily indicate disease.",
    "Values within range do not guarantee good health.",
    "Only supported and readable laboratory results are analyzed.",
    "Verify results against the original report and review them with a healthcare professional.",
]
STATUS_TEXT = {
    "below_range": "This result is below the reference range stated in your report.",
    "above_range": "This result is above the reference range stated in your report.",
    "within_range": "This result is within the reference range stated in your report.",
    "indeterminate": "This result cannot be compared safely. Its value, unit, range or extraction may need verification.",
}


def build_explanation(tests, sources, quotes, questions, warnings, consent):
    outside = sum(t.status in ("below_range", "above_range") for t in tests)
    within = sum(t.status == "within_range" for t in tests)
    unknown = len(tests) - outside - within
    pages = {
        int(s.title.rsplit(" ", 1)[-1]): i
        for i, s in enumerate(sources, 1)
        if s.type.value == "record" and s.title.rsplit(" ", 1)[-1].isdigit()
    }
    parameters = []
    assigned = set()
    for index, test in enumerate(tests, 1):
        cited = []
        for qindex, (quote, citation) in enumerate(quotes):
            if test.name == "Hemoglobin" and re.search(
                r"\b(?:a1c|hba1c|glycated)\b", quote, re.I
            ):
                continue
            if any(
                re.search(r"\b" + re.escape(alias) + r"\b", quote, re.I)
                for alias in ALIASES.get(test.name, [test.name])
            ):
                cited.append(CitedExplanation(text=quote, citation_ids=[citation]))
                assigned.add(qindex)
        parameters.append(
            ParameterExplanation(
                parameter_id=test.parameter_id or f"parameter-{index}",
                what_it_measures=cited,
                range_explanation=STATUS_TEXT[test.status]
                + " A healthcare professional can interpret it alongside your symptoms and medical history.",
                citation_ids=(
                    [pages[test.source_page]] if test.source_page in pages else []
                ),
            )
        )
    context = [
        CitedExplanation(text=quote, citation_ids=[citation])
        for index, (quote, citation) in enumerate(quotes)
        if index not in assigned
    ]
    return StructuredExplanation(
        mode="llm_assisted" if quotes else "fallback" if consent else "local",
        overall_summary=f"Your report contains {len(tests)} analyzed parameters: {within} within the stated range, {outside} outside it, and {unknown} indeterminate. Discuss results outside their stated range with your healthcare professional.",
        parameter_explanations=parameters,
        educational_context=context,
        doctor_discussion_questions=list(questions),
        limitations=list(dict.fromkeys([*LIMITATIONS, *warnings])),
        medical_disclaimer="This analysis is for educational purposes and is not a medical diagnosis or a prescription.",
        urgent_care_guidance="If you currently have severe symptoms or the report is flagged critical, seek urgent professional assessment. For an emergency, contact local emergency services. A range flag alone does not establish an emergency.",
        citation_ids=list(range(1, len(sources) + 1)),
    )
