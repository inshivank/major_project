"""Synthetic security/HTTP regressions for parsed PDF validation."""

import hashlib
from pathlib import Path
import pymupdf as fitz
import pytest
from fastapi.testclient import TestClient
from backend.agents.report_agent import ReportAgent
from backend.config.settings import Settings
from backend.main import app, get_report_agent
from backend.reports.errors import ReportError
from backend.reports.extraction import DocumentExtractor
from backend.reports.parser import parse
from backend.reports.pdf_security import pdf_names
from scripts.generate_report_fixtures import build_fixtures, ROWS


@pytest.fixture(scope="module")
def documents():
    return build_fixtures()


@pytest.mark.parametrize(
    "name",
    [
        "cbc_text.pdf",
        "safe_keyword_metadata.pdf",
        "safe_keyword_text.pdf",
        "safe_name_prefix.pdf",
        "safe_nested_string.pdf",
        "safe_hex_string.pdf",
    ],
)
def test_legitimate_pdf_strings_and_prefix_names_are_accepted(documents, name):
    data = documents[name]
    with fitz.open(stream=data, filetype="pdf") as doc:
        assert not doc.is_repaired and not doc.needs_pass
        assert doc.embfile_count() == 0
    result = DocumentExtractor().extract(data)
    assert result.page_count == 1 and result.segments[0].page == 1


@pytest.mark.parametrize(
    "name",
    [
        "unsafe_attachment.pdf",
        "unsafe_javascript.pdf",
        "unsafe_launch.pdf",
        "unsafe_automatic.pdf",
        "unsafe_additional.pdf",
        "unsafe_rich_media.pdf",
        "unsafe_embedded_object.pdf",
        "unsafe_escaped.pdf",
        "unsafe_compressed.pdf",
    ],
)
def test_all_controlled_active_content_is_rejected(documents, name):
    with pytest.raises(ReportError) as error:
        DocumentExtractor().extract(documents[name])
    assert error.value.code == "unsafe_pdf" and error.value.status_code == 422


def test_escaped_and_compressed_fixtures_really_require_parsed_objects(documents):
    assert b"/J#61vaScript" in documents["unsafe_escaped.pdf"]
    data = documents["unsafe_compressed.pdf"]
    assert b"/JavaScript" not in data and b"/JS" not in data
    with fitz.open(stream=data, filetype="pdf") as doc:
        assert not doc.is_repaired
        assert any("/ObjStm" in doc.xref_object(n) for n in range(1, doc.xref_length()))
        assert any(
            "/JavaScript" in doc.xref_object(n) for n in range(1, doc.xref_length())
        )


@pytest.mark.parametrize(
    "value",
    [
        "<< /Title (/JS \\(nested\\) harmless) /Author (Nested (text /Launch)) >>",
        "<< /Title <2f4a617661536372697074> % /JS in a comment\n /Subject (safe) >>",
    ],
)
def test_lexer_ignores_string_and_comment_contents(value):
    names = list(pdf_names(value, lambda: None))
    assert not {"JS", "Launch", "JavaScript"}.intersection(names)
    assert "Title" in names


@pytest.mark.parametrize(
    "name",
    ["JS", "JavaScript", "Launch", "OpenAction", "AA", "RichMedia", "EmbeddedFile"],
)
def test_lexer_decodes_escaped_prohibited_names(name):
    escaped = "".join("#" + format(ord(char), "02x") for char in name)
    assert list(pdf_names("<< /" + escaped + " null >>", lambda: None)) == [name]


def test_lexer_does_not_match_name_prefixes():
    assert list(
        pdf_names(
            "<< /JS-Documentation (safe) /JavaScriptNotes (safe) >>", lambda: None
        )
    ) == ["JS-Documentation", "JavaScriptNotes"]


def test_lexer_checks_deadline_inside_long_strings():
    calls = []

    def deadline():
        calls.append(1)
        if len(calls) > 2:
            raise ReportError("processing_timeout", "Synthetic deadline", 504)

    with pytest.raises(ReportError) as error:
        list(pdf_names("(" + ("x" * 20000) + ")", deadline))
    assert error.value.code == "processing_timeout"


def test_fixture_cbc_measurements_and_document_ranges(documents):
    tests, kind, warnings = parse(
        DocumentExtractor().extract(documents["cbc_text.pdf"])
    )
    assert kind == "CBC" and not warnings
    assert [t.name for t in tests] == [
        "Hemoglobin",
        "White Blood Cell Count",
        "Platelets",
    ]
    assert [(t.value, t.unit, t.reference_range) for t in tests] == [
        row[1:] for row in ROWS
    ]
    assert [t.status for t in tests] == ["below_range", "above_range", "within_range"]


@pytest.mark.parametrize(
    "name,code",
    [
        ("encrypted.pdf", "encrypted_pdf"),
        ("corrupt.pdf", "corrupt_pdf"),
        ("unsupported.txt", "unsupported_file"),
    ],
)
def test_invalid_fixtures_remain_rejected(documents, name, code):
    with pytest.raises(ReportError) as error:
        DocumentExtractor().extract(documents[name])
    assert error.value.code == code


def test_object_count_limit_remains_enforced():
    with fitz.open() as doc:
        doc.new_page()
        while doc.xref_length() <= 20000:
            doc.update_object(doc.get_new_xref(), "null")
        data = doc.tobytes()
    with pytest.raises(ReportError) as error:
        DocumentExtractor().extract(data)
    assert error.value.status_code == 413 and error.value.code == "unsafe_pdf"


@pytest.mark.parametrize(
    "name", ["cbc_text.pdf", "safe_keyword_metadata.pdf", "safe_keyword_text.pdf"]
)
def test_actual_multipart_payload_matches_pipeline_digest(documents, name):
    data = documents[name]
    digests = []

    class RecordingExtractor(DocumentExtractor):
        def extract(self, payload):
            digests.append(hashlib.sha256(payload).hexdigest())
            return super().extract(payload)

    app.dependency_overrides[get_report_agent] = lambda: ReportAgent(
        extractor=RecordingExtractor()
    )
    try:
        response = TestClient(app).post(
            "/reports/analyze",
            files={"file": (name, data, "application/pdf")},
            data={"external_llm_consent": "false"},
        )
        assert response.status_code == 200, response.text
        assert digests == [hashlib.sha256(data).hexdigest()]
        assert response.json()["external_llm_used"] is False
    finally:
        app.dependency_overrides.clear()


@pytest.mark.parametrize(
    "name", ["unsafe_attachment.pdf", "unsafe_compressed.pdf", "unsafe_escaped.pdf"]
)
def test_api_keeps_structured_security_errors(documents, name):
    app.dependency_overrides[get_report_agent] = lambda: ReportAgent(
        extractor=DocumentExtractor()
    )
    try:
        response = TestClient(app).post(
            "/reports/analyze", files={"file": (name, documents[name])}
        )
        assert response.status_code == 422
        assert response.json()["detail"]["code"] == "unsafe_pdf"
    finally:
        app.dependency_overrides.clear()


@pytest.mark.parametrize("name", ["cbc_scanned.pdf", "cbc.png", "cbc.jpg"])
def test_generated_raster_uploads_keep_ocr_uncertainty(documents, name):
    from scripts.generate_report_fixtures import TEXT

    class LocalOCRDouble:
        def read(self, image, timeout):
            assert image.width > 0 and image.height > 0 and timeout > 0
            return TEXT

    extractor = DocumentExtractor(ocr=LocalOCRDouble())
    app.dependency_overrides[get_report_agent] = lambda: ReportAgent(
        extractor=extractor
    )
    try:
        response = TestClient(app).post(
            "/reports/analyze",
            files={"file": (name, documents[name])},
            data={"external_llm_consent": "false"},
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert [
            (test["value"], test["unit"], test["reference_range"])
            for test in body["tests"]
        ] == [row[1:] for row in ROWS]
        assert all(
            test["uncertain"]
            and test["status"] == "indeterminate"
            and test["source_page"] == 1
            for test in body["tests"]
        )
        assert body["external_llm_used"] is False and body["status"] == "partial"
    finally:
        app.dependency_overrides.clear()
