"""Validated report API contracts. Original measurements are never normalized."""

from typing import Literal
from pydantic import BaseModel, Field
from backend.schemas.chat import Source

RangeStatus = Literal["below_range", "within_range", "above_range", "indeterminate"]


class Segment(BaseModel):
    page: int = Field(ge=1)
    text: str
    method: Literal["text", "ocr"] = "text"
    uncertain: bool = False


class Extraction(BaseModel):
    segments: list[Segment] = Field(default_factory=list)
    page_count: int = Field(ge=1)
    warnings: list[str] = Field(default_factory=list)


class Measurement(BaseModel):
    name: str
    original_label: str
    value: str | None = None
    unit: str | None = None
    reference_range: str | None = None
    reported_flag: str | None = None
    source_page: int = Field(ge=1)
    source_type: Literal["record"] = "record"
    uncertain: bool = False
    warnings: list[str] = Field(default_factory=list)
    status: RangeStatus = "indeterminate"


class ReportMetadata(BaseModel):
    page_count: int
    extracted_pages: list[int]
    # Patient identifiers and filenames are deliberately not retained.


class ReportResponse(BaseModel):
    agent: Literal["medical_report"] = "medical_report"
    status: Literal["completed", "partial"]
    report_type: str
    metadata: ReportMetadata
    tests: list[Measurement]
    summary: str
    warnings: list[str] = Field(default_factory=list)
    sources: list[Source] = Field(default_factory=list)
    disclaimer: str
    external_llm_used: bool = False
