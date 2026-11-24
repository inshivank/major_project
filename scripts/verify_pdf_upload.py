"""Verify synthetic PDF/image uploads against an actual loopback CoreCare server."""

from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import re
from urllib.parse import urlsplit
import httpx
from backend.config.settings import PROJECT_ROOT, settings
from backend.rag.retriever import Retriever
from backend.reports.extraction import DocumentExtractor
from backend.reports.parser import parse
from backend.schemas.report import ReportResponse
from scripts.generate_report_fixtures import build_fixtures, ROWS


def check_report(body: dict, ocr: bool, expected_rows: bool = True) -> ReportResponse:
    report = ReportResponse.model_validate(body)
    assert report.agent == "medical_report"
    if expected_rows:
        assert [test.name for test in report.tests] == [
            "Hemoglobin",
            "White Blood Cell Count",
            "Platelets",
        ]
        assert [
            (test.value, test.unit, test.reference_range) for test in report.tests
        ] == [row[1:] for row in ROWS]
        assert [test.status for test in report.tests] == (
            ["indeterminate"] * 3
            if ocr
            else ["below_range", "above_range", "within_range"]
        )
        assert all(
            test.source_page == 1 and test.uncertain is ocr for test in report.tests
        )
    references = [int(n) for n in re.findall(r"\[(\d+)\]", report.summary)]
    assert report.disclaimer
    assert all(1 <= n <= len(report.sources) for n in references)
    if report.tests:
        assert references and report.sources[0].type.value == "record"
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8001")
    parser.add_argument(
        "--consent",
        action="store_true",
        help="Authorize synthetic report and existing Week 2 live API checks.",
    )
    args = parser.parse_args()
    parsed = urlsplit(args.base_url)
    if parsed.scheme != "http" or parsed.hostname not in {
        "127.0.0.1",
        "localhost",
        "::1",
    }:
        parser.error("Only a loopback HTTP server is supported.")
    output = PROJECT_ROOT / "reports/runtime"
    output.mkdir(parents=True, exist_ok=True)
    fixtures = build_fixtures()
    evidence = {
        "synthetic_only": True,
        "base_url": args.base_url,
        "explicit_consent": args.consent,
        "checks": {},
    }

    def save():
        (output / "pdf_http_verification.json").write_text(
            json.dumps(evidence, indent=2) + "\n", encoding="utf-8"
        )

    with httpx.Client(
        base_url=args.base_url,
        trust_env=False,
        timeout=settings.report_processing_timeout_seconds + 15,
    ) as client:
        schema = client.get("/openapi.json")
        schema.raise_for_status()
        evidence["application"] = schema.json()["info"]
        assert evidence["application"]["title"] == "CoreCare"

        def upload(label, data, filename, consent=False):
            response = client.post(
                "/reports/analyze",
                files={"file": (filename, data)},
                data={"external_llm_consent": str(consent).lower()},
            )
            body = response.json()
            evidence["checks"][label] = {
                "status": response.status_code,
                "sha256": hashlib.sha256(data).hexdigest(),
                "response": body,
            }
            save()
            return response, body

        root = PROJECT_ROOT / "test_report.pdf"
        if root.exists():
            data = root.read_bytes()
            response, body = upload("original_pdf", data, root.name)
            assert response.status_code == 200, body
            expected = parse(DocumentExtractor().extract(data))[0]
            report = check_report(body, False, expected_rows=False)
            assert [test.model_dump() for test in report.tests] == [
                test.model_dump() for test in expected
            ]
            assert not report.external_llm_used
        for label, name, ocr in [
            ("local_text_pdf", "cbc_text.pdf", False),
            ("scanned_pdf", "cbc_scanned.pdf", True),
            ("png", "cbc.png", True),
            ("jpeg", "cbc.jpg", True),
        ]:
            response, body = upload(label, fixtures[name], name)
            assert response.status_code == 200, body
            report = check_report(body, ocr)
            assert not report.external_llm_used
        for name in fixtures:
            if name.startswith("safe_"):
                response, body = upload(name, fixtures[name], name)
                assert response.status_code == 200, body
                assert not body["external_llm_used"]
            elif name.startswith("unsafe_"):
                response, body = upload(name, fixtures[name], name)
                assert (
                    response.status_code == 422
                    and body["detail"]["code"] == "unsafe_pdf"
                ), body
        if args.consent:
            response, body = upload(
                "consented_text_pdf", fixtures["cbc_text.pdf"], "cbc_text.pdf", True
            )
            assert response.status_code == 200, body
            report = check_report(body, False)
            if settings.groq_api_key.strip():
                assert (
                    report.external_llm_used and report.status == "completed"
                ), report.warnings
                references = [
                    (i, source)
                    for i, source in enumerate(report.sources, 1)
                    if source.type.value == "reference"
                ]
                assert references, report.warnings
                stored = Retriever().collection.get(include=["documents", "metadatas"])
                for index, source in references:
                    assert (
                        f"[{index}]" in report.summary and source.snippet and source.url
                    )
                    assert any(
                        source.snippet in text and source.url == metadata.get("url")
                        for text, metadata in zip(
                            stored["documents"], stored["metadatas"]
                        )
                    )
                evidence["live_groq"] = "verified"
            else:
                evidence["live_groq"] = "blocked_missing_key"
            # A general educational question; no patient information is sent.
            chat = client.post(
                "/chat", json={"message": "What does a complete blood count measure?"}
            )
            evidence["checks"]["week2_chat"] = {
                "status": chat.status_code,
                "response": chat.json(),
            }
            save()
            assert chat.status_code == 200, chat.json()
            assert (
                chat.json()["agent"] == "patient_agent"
                and chat.json()["status"] == "ok"
            )
            assert chat.json()["answer"] and chat.json()["sources"]
        evidence["overall"] = (
            "verified"
            if not args.consent or evidence.get("live_groq") == "verified"
            else "partial"
        )
        save()
    print(
        json.dumps(
            {
                "application": evidence["application"],
                "overall": evidence["overall"],
                "live_groq": evidence.get("live_groq", "not_requested"),
                "checks": {
                    name: {
                        "http": item["status"],
                        "agent_status": item["response"].get("status"),
                        "external_llm_used": item["response"].get("external_llm_used"),
                    }
                    for name, item in evidence["checks"].items()
                },
            },
            indent=2,
        )
    )
    return 0 if evidence["overall"] == "verified" else 2


if __name__ == "__main__":
    raise SystemExit(main())
