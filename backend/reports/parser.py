"""Conservative lab-row parsing. Unknown/ambiguous layouts are never guessed."""

import re
from backend.schemas.report import Extraction, Measurement
from backend.reports.ranges import analyze

# Longest aliases are tried first; labels must start a row.
ALIASES = {
    "Hemoglobin": ["hemoglobin", "haemoglobin", "hgb", "hb"],
    "White Blood Cell Count": [
        "white blood cell count",
        "white blood cells",
        "wbc count",
        "wbc",
        "total leukocyte count",
        "tlc",
    ],
    "Platelets": ["platelet count", "platelets", "plt"],
    "Red Blood Cell Count": ["red blood cell count", "rbc count", "rbc"],
    "Hematocrit": ["hematocrit", "haematocrit", "hct", "pcv"],
    "MCV": ["mcv"],
    "MCH": ["mch"],
    "MCHC": ["mchc"],
    "Glucose": [
        "fasting blood glucose",
        "fasting blood sugar",
        "blood glucose",
        "glucose fasting",
        "glucose",
        "fbs",
        "random blood sugar",
    ],
    "HbA1c": ["glycated hemoglobin", "hba1c", "a1c"],
    "Total Cholesterol": ["total cholesterol", "cholesterol total"],
    "HDL Cholesterol": ["hdl cholesterol", "hdl-c", "hdl"],
    "LDL Cholesterol": ["ldl cholesterol", "ldl-c", "ldl"],
    "Triglycerides": ["triglycerides", "triglyceride"],
    "Creatinine": ["serum creatinine", "creatinine"],
    "Urea": ["blood urea", "urea"],
    "BUN": ["blood urea nitrogen", "bun"],
    "eGFR": ["estimated glomerular filtration rate", "egfr"],
    "ALT": ["alanine aminotransferase", "alt (sgpt)", "sgpt", "alt"],
    "AST": ["aspartate aminotransferase", "ast (sgot)", "sgot", "ast"],
    "ALP": ["alkaline phosphatase", "alp"],
    "Bilirubin": ["total bilirubin", "bilirubin total", "bilirubin"],
    "Albumin": ["serum albumin", "albumin"],
    "TSH": ["thyroid stimulating hormone", "tsh"],
    "Free T4": ["free thyroxine", "free t4", "ft4"],
    "Free T3": ["free triiodothyronine", "free t3", "ft3"],
}
LABELS = sorted(
    [(alias, name) for name, aliases in ALIASES.items() for alias in aliases],
    key=lambda pair: -len(pair[0]),
)
VALUE = r"(?:[<>≤≥]=?\s*)?[+-]?(?:\d+(?:\.\d+)?|\.\d+)|negative|positive|trace|pending|N/?A|[-–]"
# Units are accepted syntactically, never inferred or converted.
UNIT = (
    r"(?:%|[a-zA-Zµμ][a-zA-Z0-9µμ/^.*³²%+-]*|\d+(?:\^\d+|\*\d+\^\d+|[³⁶⁹])/[a-zA-Zµμ]+)"
)
ROW = re.compile(
    rf"^\s*(?P<value>{VALUE})(?:\s+(?P<flag>H|L|high|low|critical|\*|↑|↓))?(?:\s+(?P<unit>{UNIT}))?(?:\s+(?P<range>.+?))?\s*$",
    re.I,
)


def parse(extraction: Extraction) -> tuple[list[Measurement], str, list[str]]:
    tests, warnings = [], []
    for segment in extraction.segments:
        for line in segment.text.splitlines():
            line = line.strip()
            for alias, name in LABELS:
                match = re.match(r"^" + re.escape(alias) + r"(?=$|[\s:|])", line, re.I)
                if not match:
                    continue
                label = line[: match.end()]
                tail = line[match.end() :].strip(" :|\t")
                # Pipe-separated and whitespace rows share the same conservative grammar.
                tail = re.sub(r"\s*\|\s*", " ", tail)
                row = ROW.fullmatch(tail)
                values = row.groupdict() if row else {}
                unit, reference = values.get("unit"), values.get("range")
                flag = values.get("flag")
                if unit and unit.casefold() in ("h", "l", "high", "low", "critical"):
                    flag, unit = unit, None
                if reference:
                    end_flag = re.search(
                        r"\s+(H|L|high|low|critical|↑|↓)\s*$", reference, re.I
                    )
                    if end_flag:
                        flag = end_flag[1]
                        reference = reference[: end_flag.start()].rstrip()
                test = Measurement(
                    name=name,
                    original_label=label,
                    value=values.get("value"),
                    unit=unit,
                    reference_range=reference,
                    reported_flag=flag,
                    source_page=segment.page,
                    uncertain=segment.uncertain or not bool(row),
                )
                if not row:
                    test.warnings.append(
                        "Unrecognized or missing result; verify the original row."
                    )
                tests.append(analyze(test))
                break
    if not tests:
        warnings.append(
            "No supported laboratory rows were identified; no measurements were invented."
        )
    if len({t.name for t in tests}) < len(tests):
        warnings.append(
            "Repeated test names retained separately; dates and specimens are not inferred."
        )
    names = {t.name for t in tests}
    groups = []
    if names & {
        "Hemoglobin",
        "White Blood Cell Count",
        "Platelets",
        "MCV",
        "Hematocrit",
    }:
        groups.append("CBC")
    if names & {
        "Total Cholesterol",
        "HDL Cholesterol",
        "LDL Cholesterol",
        "Triglycerides",
    }:
        groups.append("Lipid profile")
    if names & {"Creatinine", "Urea", "BUN", "eGFR"}:
        groups.append("Kidney function")
    if names & {"ALT", "AST", "ALP", "Bilirubin", "Albumin"}:
        groups.append("Liver function")
    if names & {"TSH", "Free T4", "Free T3"}:
        groups.append("Thyroid function")
    if names & {"Glucose", "HbA1c"}:
        groups.append("Glucose/HbA1c")
    return tests, ", ".join(groups) or "Unclassified", warnings
