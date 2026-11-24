"""Actual Windows/report runtime check using only generated synthetic documents.

No dependency overrides or fake OCR/retrieval/LLM are used. Starts a loopback-only
Uvicorn server and writes evidence to the ignored reports/runtime directory.
--consent authorizes one report explanation workflow if a key is configured.
An absent key records a blocker; it is never replaced with a fake response.
"""

from __future__ import annotations

import argparse
import io
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import time

import httpx
from PIL import Image, ImageDraw, ImageFont
import pymupdf
import pytesseract

from backend.config.settings import PROJECT_ROOT, settings
from backend.rag.retriever import Retriever
from backend.reports.extraction import DocumentExtractor
from backend.schemas.report import ReportResponse

ROWS = [
    ("Hemoglobin", "10.2", "g/dL", "12-16", "below_range"),
    ("WBC", "13.0", "K/uL", "4-11", "above_range"),
    ("Platelets", "250", "K/uL", "150-400", "within_range"),
]
NAMES = ["Hemoglobin", "White Blood Cell Count", "Platelets"]
TEXT = "SYNTHETIC CBC - NOT A PATIENT RECORD\n\n" + "\n".join(
    " ".join(row[:4]) for row in ROWS
)


def make_documents(output: Path) -> dict[str, Path]:
    font_path = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / "arial.ttf"
    font = (
        ImageFont.truetype(str(font_path), 42)
        if font_path.exists()
        else ImageFont.load_default(size=42)
    )
    with Image.new("RGB", (1900, 600), "white") as image:
        ImageDraw.Draw(image).multiline_text(
            (50, 50), TEXT, font=font, fill="black", spacing=25
        )
        image.save(output / "synthetic_cbc.png")
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
    with pymupdf.open() as document:
        page = document.new_page(width=950, height=300)
        page.insert_image(page.rect, stream=buffer.getvalue())
        document.save(output / "synthetic_cbc_scanned.pdf")
    with pymupdf.open() as document:
        document.new_page().insert_text((40, 60), TEXT, fontsize=12)
        document.save(output / "synthetic_cbc_text.pdf")
    return {
        name: output / filename
        for name, filename in (
            ("png", "synthetic_cbc.png"),
            ("scanned_pdf", "synthetic_cbc_scanned.pdf"),
            ("text_pdf", "synthetic_cbc_text.pdf"),
        )
    }


def validate_response(body: dict, ocr: bool) -> ReportResponse:
    report = ReportResponse.model_validate(body)
    assert report.agent == "medical_report" and report.report_type == "CBC"
    assert report.metadata.extracted_pages == [1]
    assert [test.name for test in report.tests] == NAMES
    for test, row in zip(report.tests, ROWS):
        assert (test.value, test.unit, test.reference_range) == row[
            1:4
        ], test.model_dump()
        assert test.source_page == 1 and test.source_type == "record"
        assert test.status == ("indeterminate" if ocr else row[4]), test.model_dump()
        assert test.uncertain is ocr
    assert report.disclaimer
    references = [int(number) for number in re.findall(r"\[(\d+)\]", report.summary)]
    assert references and all(
        1 <= number <= len(report.sources) for number in references
    )
    assert report.sources[0].type.value == "record"
    for index, source in enumerate(report.sources, 1):
        if source.type.value == "reference":
            assert source.url and source.snippet and f"[{index}]" in report.summary
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--consent",
        action="store_true",
        help="Allow a synthetic report explanation to use the configured Groq provider.",
    )
    args = parser.parse_args()
    output = PROJECT_ROOT / "reports" / "runtime"
    output.mkdir(parents=True, exist_ok=True)
    documents = make_documents(output)
    if settings.tesseract_cmd:
        pytesseract.pytesseract.tesseract_cmd = settings.tesseract_cmd
    evidence = {
        "synthetic_only": True,
        "ocr_version": str(pytesseract.get_tesseract_version()),
        "groq_key_configured": bool(settings.groq_api_key.strip()),
        "explicit_consent": args.consent,
        "uploads": {},
    }
    extractor = DocumentExtractor()
    for kind in ("png", "scanned_pdf"):
        extraction = extractor.extract(documents[kind].read_bytes())
        assert extraction.segments[0].method == "ocr"
        (output / f"{kind}_extraction.json").write_text(
            extraction.model_dump_json(indent=2), encoding="utf-8"
        )

    # Exercise production's isolated retrieval against the actual configured collection.
    retriever = Retriever()
    chunks = retriever.retrieve_for_report(
        ["Hemoglobin white blood cell platelets CBC laboratory test patient education"],
        timeout=settings.report_processing_timeout_seconds,
        memory_mb=settings.report_worker_memory_mb,
    )
    assert chunks and any(
        "complete-blood-count-cbc" in (chunk.url or "") for chunk in chunks
    )
    evidence["retrieval"] = {
        "collection": settings.collection_name,
        "count": retriever.count(),
        "sources": [
            dict(title=c.title, url=c.url, score=c.score, text=c.text) for c in chunks
        ],
    }
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    server = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "backend.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--no-access-log",
            "--log-level",
            "warning",
        ],
        cwd=PROJECT_ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    try:
        with httpx.Client(
            base_url=f"http://127.0.0.1:{port}",
            timeout=settings.report_processing_timeout_seconds + 10,
            trust_env=False,
        ) as client:
            ready_deadline = time.monotonic() + 30
            while True:
                try:
                    if client.get("/").status_code == 200:
                        break
                except httpx.TransportError:
                    pass
                if server.poll() is not None or time.monotonic() >= ready_deadline:
                    raise RuntimeError("Local verification server did not start.")
                time.sleep(0.1)
            for kind, path in documents.items():
                # A single consented report workflow; OCR-only uploads never call Groq.
                consent = args.consent and kind == "text_pdf"
                response = client.post(
                    "/reports/analyze",
                    files={"file": (path.name, path.read_bytes())},
                    data={"external_llm_consent": str(consent).lower()},
                )
                assert response.status_code == 200, (
                    kind,
                    response.status_code,
                    response.text,
                )
                report = validate_response(response.json(), ocr=kind != "text_pdf")
                (output / f"{kind}_response.json").write_text(
                    report.model_dump_json(indent=2), encoding="utf-8"
                )
                evidence["uploads"][kind] = dict(
                    http_status=response.status_code,
                    status=report.status,
                    tests=len(report.tests),
                    range_statuses=[t.status for t in report.tests],
                    external_llm_used=report.external_llm_used,
                    sources=len(report.sources),
                    warnings=report.warnings,
                )
                if consent and evidence["groq_key_configured"]:
                    assert report.external_llm_used and any(
                        s.type.value == "reference" for s in report.sources
                    ), (
                        "Live explanation did not yield validated reference citations.",
                        {
                            "external_llm_used": report.external_llm_used,
                            "warnings": report.warnings,
                            "source_types": [
                                source.type.value for source in report.sources
                            ],
                        },
                    )
                    # Match every external quotation to an actual stored corpus chunk.
                    stored = retriever.collection.get(
                        include=["documents", "metadatas"]
                    )
                    for source in report.sources:
                        if source.type.value == "reference":
                            assert any(
                                source.snippet in text
                                and metadata.get("url") == source.url
                                for text, metadata in zip(
                                    stored["documents"], stored["metadatas"]
                                )
                            )
    finally:
        server.terminate()
        try:
            server.wait(timeout=10)
        except subprocess.TimeoutExpired:
            server.kill()
            server.wait(timeout=5)
    evidence["live_groq"] = (
        ("verified" if evidence["groq_key_configured"] else "blocked_missing_key")
        if args.consent
        else "not_requested"
    )
    evidence["overall"] = (
        "partial"
        if evidence["live_groq"] == "blocked_missing_key"
        else "verified_requested_checks"
    )
    (output / "verification.json").write_text(
        json.dumps(evidence, indent=2) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {key: value for key, value in evidence.items() if key != "retrieval"},
            indent=2,
        )
    )
    print(f'Evidence: {output / "verification.json"}')
    return 2 if evidence["overall"] == "partial" else 0


if __name__ == "__main__":
    raise SystemExit(main())
