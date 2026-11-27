# Week 4 PDF upload fix and runtime verification

Verified 2026-11-24 on Windows, Python 3.12.10, project `.venv`, PyMuPDF binding 2.1.
Branch: `main`. Initial Git state was clean except the user's untracked
`test_report.pdf`; that file was preserved byte-for-byte. No commit or push was made.

## 1. Original problem

Swagger at `http://127.0.0.1:8001/docs` reportedly returned HTTP 422:

```json
{"detail":{"code":"unsafe_pdf","message":"PDF attachments and active content are not supported."}}
```

## 2. Confirmed root cause and scope of the conclusion

The validator searched for byte substrings such as `/JS` anywhere in a PDF, then
searched serialized object text without distinguishing name tokens from strings.
That rejects harmless title text, page text, nested/hex strings, and names such as
`/JS-Documentation`. A PDF does not gain JavaScript merely by mentioning that word.

This defect was reproduced before changing application code, directly and over the
actual API, using controlled harmless metadata. The exact failing predicate was the
raw `any(token in data ...)` check with zero embedded attachments. The second regex
also confused decoded strings with names (demonstrated by the hex-string fixture).

Important limitation: the user's original `test_report.pdf` did NOT fail during this
investigation. Direct extraction, TestClient and the existing port-8001 API all
accepted it before changes. Therefore the reported historical Swagger request cannot
be conclusively attributed to this defect without its uploaded bytes. A different
selected file or historical server state is possible, but was not established.
No stale or wrong-project server was found. The confirmed false-positive defect was
fixed without pretending to reproduce an error that the supplied file did not show.

## 3. Before-fix reproduction and process evidence

Original supplied PDF: 956 bytes; SHA256
`0ba6461c81cfe3884b4a33926b6b6fb34bc04aa749987d905da00e6f7d03b645`.
It has no embedded files, no restricted raw tokens and ordinary catalog/page/font/
content-stream objects. TestClient recorded the same hash at the extraction boundary.
Both TestClient and actual HTTP returned 200 before changes.

The existing server's OpenAPI title was `CoreCare`, version `0.4.0`. Its command was
project `.venv/Scripts/python.exe -m uvicorn backend.main:app --reload --port 8001`,
with working directory `C:/Users/Aanya Aggarwal/Downloads/major_project`. The loaded
extraction module in the inspection process was this project's
`backend/reports/extraction.py`. Windows also reports the underlying base-Python
redirector child; the Uvicorn parent uses the project virtual environment.
Other projects' Python processes/ports were identified and left untouched.

Confirmed false-positive fixture: `tests/fixtures/reports/safe_keyword_metadata.pdf`.
SHA256: `dea3b03ab3f7411065653ee382016cfe99b0986342a57c221536d497c76ae41f`.
The exact same bytes returned 422 before and 200 after the fix; the before/after
hashes were asserted equal. Evidence: `http_false_positive_before.json` and
`http_false_positive_after.json` in this directory. Five harmless fixture variants
were rejected before; all five are accepted now. Nine unsafe variants were rejected
both before and after.

## 4. Files modified or created

Modified tracked files:

- `backend/reports/extraction.py`: delegate active-content checks to parsed-object validation.
- `README.md`: fixture generation, exact startup/API instructions and troubleshooting.

New source/test files:

- `backend/reports/pdf_security.py`: lexical name inspection of MuPDF-parsed objects.
- `scripts/generate_report_fixtures.py`: deterministic report content and inert security-fixture generator.
- `scripts/verify_pdf_upload.py`: real loopback HTTP upload matrix, consent and corpus-citation checks.
- `tests/test_pdf_security.py`: 41 new regression cases; existing tests unchanged.

New synthetic files under `tests/fixtures/reports/`:

- `cbc.jpg`
- `cbc.png`
- `cbc_scanned.pdf`
- `cbc_text.pdf`
- `corrupt.pdf`
- `encrypted.pdf`
- `safe_hex_string.pdf`
- `safe_keyword_metadata.pdf`
- `safe_keyword_text.pdf`
- `safe_name_prefix.pdf`
- `safe_nested_string.pdf`
- `unsafe_additional.pdf`
- `unsafe_attachment.pdf`
- `unsafe_automatic.pdf`
- `unsafe_compressed.pdf`
- `unsafe_embedded_object.pdf`
- `unsafe_escaped.pdf`
- `unsafe_javascript.pdf`
- `unsafe_launch.pdf`
- `unsafe_rich_media.pdf`
- `unsupported.txt`

Generated ignored evidence under `reports/runtime/`:

- `week4_pdf_fix_verification.md` (this report).
- `pdf_before_investigation.json`: supplied-PDF hash, actual responses and process metadata.
- `validator_before.json`, `validator_after.json`: controlled fixture acceptance/rejection.
- `http_false_positive_before.json`, `http_false_positive_after.json`: identical-byte HTTP comparison.
- `pdf_http_verification.json`: complete HTTP matrix with synthetic response bodies and file hashes.
- `pdf_fix_without_consent.json`, `pdf_fix_with_consent.json`: sanitized sample responses.
- `verification.json`: refreshed existing runtime-verifier result.

The original runtime verifier also regenerated its existing synthetic artifacts.
The temporary investigation script and dependency override were removed after use;
no production debug endpoint, instrumentation or sensitive logging remains.
The user's original `test_report.pdf` is not a newly generated or modified file.

## 5. Implementation details

MuPDF first resolves each xref, including objects held inside compressed object streams.
A small PDF lexer then distinguishes actual `/Name` tokens from literal strings,
nested/escaped string contents, hex strings and comments. Name escapes (`#xx`) are
decoded only inside names. Exact prohibited names are rejected, including when
unreferenced; binary stream bytes and arbitrary text are no longer treated as names.
The full parsed object space is still scanned rather than only the catalog.

This replaces the faulty raw-byte/regex checks with equivalent name-aware protections,
not a bypass for any file or fixture. No parser/range, LLM, consent or citation logic
was modified, and no dependencies were added.

## 6. Security protections preserved

- Attachments: explicit embedded-file count plus `/EmbeddedFile` object-name checks.
- JavaScript/launch: `/JavaScript`, `/JS` and `/Launch` names rejected.
- Automatic/additional actions: `/OpenAction` and `/AA` rejected.
- Rich media: `/RichMedia` rejected.
- Escaped names: decoded before comparison; all prohibited-name escapes tested.
- Compressed object streams: inspected through resolved MuPDF xrefs; controlled
  fixture has no raw `/JavaScript` or `/JS` tokens but is still rejected.
- Encrypted/repaired/corrupt documents: existing checks retained.
- File, page, object, image and text limits: retained; object limit remains 20,000.
- Processing deadline, native-worker memory monitoring and temporary cleanup: retained.
- Consent: false never reaches retrieval/Groq; existing spy-based no-call tests pass.
- All controlled PDF payloads are inert and were never executed.

This is a conservative active-content policy, not a general malware scanner or proof
against every possible PDF-parser vulnerability.

## 7. Regression tests added

41 parameterized cases cover safe text/metadata/hex/nested strings and prefix names;
all controlled unsafe fixtures; real escaped/compressed representations; exact decoded
names; deadline checking in long strings; the object-count limit; correct CBC values,
units/ranges and below/above/within classifications; multipart SHA256 preservation;
structured unsafe-file errors; and scanned-PDF/PNG/JPEG upload uncertainty.
Raster API unit tests use real decoding and a fake OCR dependency; actual OCR was
separately verified over HTTP. No existing assertion was removed, weakened or skipped.

## 8. Automated test results and exact commands

```powershell
.venv\Scripts\python -m pytest tests/test_pdf_security.py -q
# 41 passed in 2.33s
.venv\Scripts\python -m pytest -q
# 189 passed in 6.18s: all original 148 plus 41 new
.venv\Scripts\python -m pip check
# No broken requirements found.
git diff --check
# Passed.
git status --short -- research/colacare
# No output: untouched.
```

Final totals: **189 passed, 0 failed, 0 skipped**. An earlier targeted run passed 38
cases; three raster-API regressions were then added and the full suite rerun.

## 9. Actual HTTP API results

Tests used the real existing CoreCare server on `127.0.0.1:8001`, no mock API.

| Check | HTTP | Result |
|---|---|---|
| User's original PDF | 200 | Local extraction matches independently parsed values; no external LLM |
| Required synthetic CBC text PDF, no consent | 200 | Three exact values/ranges; below, above, within; external LLM false |
| Same CBC text PDF, explicit consent | 200 | Completed; live Groq true; no warnings; medical reference citations validated |
| Scanned CBC PDF | 200 | Real OCR; exact values/units/ranges; uncertain/indeterminate as designed |
| PNG | 200 | Real OCR; exact values/units/ranges; uncertain/indeterminate |
| JPEG | 200 | Real OCR; exact values/units/ranges; uncertain/indeterminate |
| Five harmless keyword-bearing PDF variants | 200 each | No false rejection |
| Nine controlled unsafe PDF variants | 422 each | Structured `unsafe_pdf` rejection |
| Week 2 `/chat` general CBC question | 200 | `patient_agent`, status `ok`, answer and sources |

A local-only successful response intentionally has `status=partial` because external
education was not requested; HTTP 200, structured tests and warnings distinguish this
from extraction failure. No external call occurs in this consent-disabled branch.

## 10. Groq/RAG and existing runtime verifier

```powershell
.venv\Scripts\python -m scripts.verify_pdf_upload --base-url http://127.0.0.1:8001 --consent
# Exit 0: overall=verified, live_groq=verified
.venv\Scripts\python -m scripts.verify_report_runtime --consent
# Exit 0: overall=verified_requested_checks, live_groq=verified
```

The original verifier launched/stopped its own loopback server. It passed real PDF
extraction/OCR, range analysis, actual Chroma retrieval, live consented Groq generation
and reference validation against stored corpus text/URLs. The port-8001 consented
response was completed, `external_llm_used=true`, and had no warnings. Its reference
was the actual MedlinePlus CBC corpus document. Quote matching, citation-index checks,
medical-safety filtering, and locally rendered original measurements were preserved.
No API keys, provider reasoning, real patient information or secrets were printed.

## 11. OCR results and example JSON

Tesseract `5.4.0.20240606` recovered these exact synthetic rows from PNG, JPEG and
scanned PDF:

| Test | Value/unit | Stated reference range | Text-PDF classification |
|---|---|---|---|
| Hemoglobin | 10.0 g/dL | 12.0-16.0 g/dL | below_range |
| WBC | 12000 cells/uL | 4000-11000 cells/uL | above_range |
| Platelet Count | 250000 cells/uL | 150000-450000 cells/uL | within_range |

These are synthetic fixture ranges, not inferred universal norms. OCR measurements
remain uncertain and `indeterminate`; confidence was not overridden for testing.
Full local/consented JSON examples are in the two `pdf_fix_*consent.json` files.

Confirmed harmless-metadata example, before:

```json
{"detail":{"code":"unsafe_pdf","message":"PDF attachments and active content are not supported."}}
```

The same bytes after (selected actual fields):

```json
{
  "agent": "medical_report",
  "status": "partial",
  "external_llm_used": false,
  "tests": [
    {
      "name": "Hemoglobin",
      "value": "10.0",
      "unit": "g/dL",
      "reference_range": "12.0-16.0 g/dL",
      "status": "below_range"
    },
    {
      "name": "White Blood Cell Count",
      "value": "12000",
      "unit": "cells/uL",
      "reference_range": "4000-11000 cells/uL",
      "status": "above_range"
    },
    {
      "name": "Platelets",
      "value": "250000",
      "unit": "cells/uL",
      "reference_range": "150000-450000 cells/uL",
      "status": "within_range"
    }
  ]
}
```

## 12. Manual Swagger testing

The existing CoreCare server is already running on port 8001. Reuse it, or stop your
own server before starting a replacement; do not launch competing instances.
From the project root, the explicit virtual-environment startup command is:

```powershell
.venv\Scripts\python -m uvicorn backend.main:app --reload --host 127.0.0.1 --port 8001
```

1. Open `http://127.0.0.1:8001/docs`; verify the application is CoreCare.
2. Expand `POST /reports/analyze`, select **Try it out**.
3. Clear/reselect the file input; choose the actual file
   `C:/Users/Aanya Aggarwal/Downloads/major_project/tests/fixtures/reports/cbc_text.pdf`.
   Do not paste its path into a text field or reuse a previously selected PDF.
4. Set `external_llm_consent` to `false` and execute: expect HTTP 200, three correct
   measurements and comparisons, `external_llm_used=false`, and a consent warning.
5. Set consent to `true` only to authorize the synthetic live explanation: expect
   HTTP 200, completed analysis and validated medical references.
6. Try `cbc_scanned.pdf`, `cbc.png`, `cbc.jpg`: expect HTTP 200 with OCR uncertainty.
7. For security rejection only, choose `unsafe_attachment.pdf`: expect 422 unsafe_pdf.
   Do not open/execute embedded PDF payloads in any viewer.

The supplied root `test_report.pdf` also works and is unchanged. The dedicated CBC
fixture is the recommended reproducible manual sample. Regenerate fixtures with:

```powershell
.venv\Scripts\python -m scripts.generate_report_fixtures
curl.exe -X POST "http://127.0.0.1:8001/reports/analyze" -F "file=@tests/fixtures/reports/cbc_text.pdf;type=application/pdf" -F "external_llm_consent=false"
```

## 13. Remaining limitations

No current HTTP/OCR/Groq runtime blocker was observed. The precise historical Swagger
request is unavailable, so its selected bytes cannot be reconstructed or its exact
cause claimed. The supplied file was accepted even before the fix; the separate
validator defect has exact, identical-byte before/after evidence.

OCR remains fallible and uncertain; complex layouts/handwriting, demographic inference,
clinical diagnosis, prescriptions, unit conversion, and EHR prediction remain outside
this implementation. Live providers can change availability or enforce quotas.
Research code and Week 3/5 were not modified. The API's existing deployment
access-control limitations remain. No unrelated process was terminated.
