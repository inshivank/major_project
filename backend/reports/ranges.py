"""Deterministic comparison against explicitly reported ranges only."""

import re
from decimal import Decimal, InvalidOperation
from backend.schemas.report import Measurement

NUMBER = r"[+-]?(?:\d+(?:\.\d+)?|\.\d+)"
RANGE = re.compile(rf"^\s*({NUMBER})\s*(?:-|–|—|to)\s*({NUMBER})(?:\s+(.+))?\s*$", re.I)
LIMIT = re.compile(rf"^\s*(<=|>=|<|>|≤|≥)\s*({NUMBER})(?:\s+(.+))?\s*$")


def analyze(test: Measurement) -> Measurement:
    result = test.model_copy(deep=True)
    result.status = "indeterminate"

    def warn(message):
        if message not in result.warnings:
            result.warnings.append(message)
        return result

    if result.uncertain:
        return warn("Extraction uncertain; verify against the original report.")
    if not result.unit:
        return warn("Missing unit; comparison not performed.")
    if not result.value or not re.fullmatch(NUMBER, result.value):
        return warn("Missing, qualified, or non-numeric value.")
    if not result.reference_range:
        return warn("No reference range stated in the report.")
    match = RANGE.fullmatch(result.reference_range)
    limit = LIMIT.fullmatch(result.reference_range)
    if not match and not limit:
        return warn("Ambiguous reference range.")
    unit = (match or limit).group(3)
    if unit and unit.strip().casefold() != result.unit.strip().casefold():
        return warn("Reference range unit mismatch or ambiguous qualifier.")
    try:
        value = Decimal(result.value)
        if match:
            low, high = Decimal(match[1]), Decimal(match[2])
            if low > high:
                return warn("Reversed reference range.")
            result.status = (
                "below_range"
                if value < low
                else "above_range" if value > high else "within_range"
            )
        else:
            op, bound = limit[1], Decimal(limit[2])
            if op in ("<", "<=", "≤"):
                ok = value < bound if op == "<" else value <= bound
                result.status = "within_range" if ok else "above_range"
            else:
                ok = value > bound if op == ">" else value >= bound
                result.status = "within_range" if ok else "below_range"
    except InvalidOperation:
        return warn("Invalid numeric value.")
    return result
