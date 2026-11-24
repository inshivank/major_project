"""Inspect parsed PDF names, never strings or arbitrary compressed stream bytes.

MuPDF resolves xrefs/object streams before inspection. A small PDF lexical scanner
then distinguishes name tokens from literal/hex strings in the canonical object
representation. This is a conservative active-content policy, not a malware scanner.
"""

from collections.abc import Callable, Iterator
import re
from backend.reports.errors import ReportError

PROHIBITED_NAMES = frozenset(
    {
        "JavaScript",
        "JS",
        "Launch",
        "OpenAction",
        "AA",
        "RichMedia",
        "EmbeddedFile",
    }
)
DELIMITERS = frozenset("\x00\t\n\f\r ()<>[]{}/%")
NAME_ESCAPE = re.compile(r"#([0-9a-fA-F]{2})")


def pdf_names(obj: str, check_deadline: Callable[[], object]) -> Iterator[str]:
    """Yield exact decoded name tokens outside PDF comments and string objects."""
    index = 0
    while index < len(obj):
        check_deadline()
        char = obj[index]
        if char == "%":
            while index < len(obj) and obj[index] not in "\r\n":
                index += 1
        elif char == "(":
            depth = 1
            index += 1
            while index < len(obj) and depth:
                if index % 4096 == 0:
                    check_deadline()
                if obj[index] == "\\":
                    index += 2
                    continue
                if obj[index] == "(":
                    depth += 1
                elif obj[index] == ")":
                    depth -= 1
                index += 1
            if depth:
                raise ReportError(
                    "corrupt_pdf", "A PDF object contains an invalid string."
                )
        elif char == "<" and not obj.startswith("<<", index):
            index += 1
            while index < len(obj) and obj[index] != ">":
                if index % 4096 == 0:
                    check_deadline()
                index += 1
            if index == len(obj):
                raise ReportError(
                    "corrupt_pdf", "A PDF object contains an invalid hex string."
                )
            index += 1
        elif obj.startswith("<<", index):
            index += 2
        elif char == "/":
            start = index + 1
            index = start
            while index < len(obj) and obj[index] not in DELIMITERS:
                if index % 4096 == 0:
                    check_deadline()
                index += 1
            yield NAME_ESCAPE.sub(
                lambda match: chr(int(match[1], 16)), obj[start:index]
            )
        else:
            index += 1


def validate_pdf_content(document, check_deadline: Callable[[], object]) -> None:
    """Inspect all parsed objects, including unreferenced and compressed objects."""
    if document.xref_length() > 20000:
        raise ReportError(
            "unsafe_pdf", "PDF object count exceeds the processing limit.", 413
        )
    if document.embfile_count():
        raise ReportError(
            "unsafe_pdf", "PDF attachments and active content are not supported."
        )
    for xref in range(1, document.xref_length()):
        check_deadline()
        if any(
            name in PROHIBITED_NAMES
            for name in pdf_names(document.xref_object(xref), check_deadline)
        ):
            raise ReportError("unsafe_pdf", "PDF active content is not supported.")
