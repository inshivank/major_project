# Week 4 implementation report

Status: OCR, real HTTP uploads, parsing/ranges, Chroma retrieval, live Groq generation
and external citation validation verified on Windows. All 148 offline tests pass:
the original 137 plus 11 new regressions. No key was exposed, and no commit or push
was made. The branch remains `main`; pre-existing working changes were preserved.

## Components and request flow

`POST /reports/analyze` accepts one multipart `file` plus optional
`external_llm_consent=true|false` (default false). The path is:

1. Bound request size, upload duration, field/file count and concurrent jobs.
2. Validate actual content; reject unsupported/corrupt/encrypted/active PDFs and limits.
3. Extract PDF text with same-row cell reconstruction, or rasterize pages for local
   Tesseract OCR with EXIF/orientation handling and grayscale preprocessing.
4. Parse supported laboratory labels into Pydantic measurements with page attribution.
5. Compare only safe numeric measurements against explicitly stated compatible ranges.
6. With explicit consent, retrieve through the existing Chroma collection and use the
   shared Groq service to select educational sentences from evidence.
7. Validate every selected sentence and citation, then assemble local facts,
   educational excerpts, record/reference sources, uncertainty, questions and disclaimer.

Document and report-retrieval workers have hard wall-time limits, monitored RSS
limits, child-process termination and per-job temporary-directory cleanup. LLM
requests/retries/JSON repair receive the remaining deadline budget through the
existing service. Provider failure leaves the local analysis available as partial.
OCR readings always remain uncertain and comparisons remain indeterminate.

Only canonical test names and comparison statuses go to Groq. Values, units,
identifiers, raw text, filenames and history do not. Without consent, neither report
retrieval nor Groq is invoked. Measurements cannot be added or changed by the LLM.

`POST /chat` keeps its request/response contract. The real report agent handles the
report intent with upload guidance; emergency language receives immediate guidance.
Recognized pasted measurements route deterministically before LLM classification.
Report chat history stores neutral placeholders. Uploads are stateless and are never
inserted into chat history. General, record-query and prediction behavior is retained.
No clinical models or research code were modified.

## Files created

- `backend/agents/report_agent.py`: actual report orchestration and chat guidance.
- `backend/reports/__init__.py`: package boundary.
- `backend/reports/errors.py`: safe typed errors.
- `backend/reports/upload.py`: request bounds, multipart validation and cleanup.
- `backend/reports/isolation.py`: subprocess deadlines, memory monitoring and cleanup.
- `backend/reports/extraction.py`: file-content validation, PDF extraction and local OCR.
- `backend/reports/parser.py`: deterministic supported laboratory-row parsing.
- `backend/reports/ranges.py`: numeric range and inequality comparison.
- `backend/reports/explanation.py`: consent-gated RAG and validated educational selection.
- `backend/schemas/report.py`: extraction, measurement, metadata and response contracts.
- `data/corpus/lab_tests.json`: six short original MedlinePlus-based educational summaries.
- `tests/test_reports.py`: 100 offline synthetic report tests, including parameterized cases.
- `scripts/verify_report_runtime.py`: real synthetic runtime verifier over loopback HTTP.
- `tests/test_llm_service.py`: 11 real-SDK/offline-transport regression cases.
- `WEEK4_IMPLEMENTATION_REPORT.md`: this report.

## Files modified

- `backend/main.py`: report endpoint, OpenAPI multipart schema, DI and error handler.
- `backend/agents/stubs.py`: preserve old import path for the actual report agent.
- `backend/orchestrator/orchestrator.py`: share existing dependencies; redact report history.
- `backend/orchestrator/router.py`: route recognized pasted measurements locally.
- `backend/rag/retriever.py`: lazy native initialization and bounded report retrieval
  against the same configured collection.
- `backend/llm/llm_service.py`: optional deadline budget and sanitized vendor errors/logs;
  existing calls, retry policy and JSON repair remain compatible.
- `backend/config/settings.py`, `.env.example`: validated processing limits/runtime path.
- `requirements.txt`: document libraries plus Windows-compatible grpcio/pybase64 builds.
- `.gitignore`: anchor generated `/reports/` and ignore local `.runtime/` binaries/cache.
- `data/corpus/SOURCES.md`: citations for the added laboratory summaries.
- `README.md`: setup, flow, usage, consent, safety, limits and testing.

## Endpoints

- New: `POST /reports/analyze` (multipart, structured `ReportResponse`).
- Existing: `POST /chat`, `GET /`, `GET /config` remain compatible.
- Multipart documentation: `/docs`.
- Structured report errors: `detail: {code, message}`. Success may be `partial` when
  extraction, comparison or educational explanation is uncertain/unavailable.

## Verification

A clean `.venv` was created with the exact versions from `requirements.txt`.
All automated tests use synthetic documents and fake external dependencies; no
network calls or Groq API key are needed. Tests exercise real decoding, parsing,
ranges, native-process termination/cleanup, default API wiring, consent, sources,
prompt-injection exclusion, existing Groq JSON repair/deadlines and Week 2 regressions.

Initial runtime verification (Python 3.12, Windows, 2026-11-14; outside the execution sandbox
because the sandbox blocked TestClient/subprocess operations):

```powershell
.venv\Scripts\python -m pytest -q
# 137 passed in 3.35s
.venv\Scripts\python -m pytest tests/test_reports.py -q
# 100 passed in 3.01s
.venv\Scripts\python -m pytest tests/test_chat_api.py tests/test_patient_agent.py tests/test_orchestrator.py tests/test_router.py tests/test_main.py tests/test_session_store.py tests/test_schemas.py -q
# 37 passed in 0.44s
.venv\Scripts\python -m pip check
# No broken requirements found.
git diff --check
# Passed (no output).
git status --short -- research/colacare
# No output: research subtree unchanged.
```

Earlier defects found by tests/checks were corrected; assertions were not weakened
and no tests were skipped. The final working tree is on `main`, with 12 modified
tracked files and 15 new source/test/documentation files; no files were staged.

## Windows runtime diagnosis and resolution

Windows Code Integrity event 3077 identified two blocked Python 3.12 modules:

- `grpcio 1.85.1`: `.venv/Lib/site-packages/grpc/_cython/cygrpc.cp312-win_amd64.pyd`.
- `pybase64 1.5.2`: `.venv/Lib/site-packages/pybase64/_pybase64.cp312-win_amd64.pyd`.

Events reported a signing-level/policy violation under policy
`{0283ac0f-fff1-49ae-ada1-8a933130cad6}`, rather than a missing DLL or Python ABI error.
The original gRPC module reported `NotSigned`. The precise reputation/rule that
distinguished accepted builds is not established; this does not imply that all
unsigned modules are blocked or that replacement wheels are signed.

Official PyPI wheels `grpcio==1.76.0` and `pybase64==1.4.2` now load successfully,
as does `chromadb==1.5.9`. They satisfy the installed dependency constraints, confirmed
by `pip check`, and are pinned for Windows in `requirements.txt`. No policy change,
security exclusion or file-unblocking command was used. This is verified for this
machine; other managed PCs may make different policy decisions. Package references:
[gRPC](https://pypi.org/project/grpcio/1.76.0/) and
[pybase64](https://pypi.org/project/pybase64/1.4.2/).

Winget's Tesseract installer returned `0x800704c7` (cancellation), including explicit
current-user mode. `--scope user` had no applicable installer. A project-local
conda-forge runtime installed, but its executable was blocked by application control.
That unused runtime and cache were removed.

The successful solution extracts the UB Mannheim publisher's verified installer
payload without executing its installer. Official 7-Zip was extracted locally from
its MSI using Windows Installer's administrative-image operation. The extracted
Tesseract executable/DLLs run under unchanged Windows controls. Version/language
checks confirmed `5.4.0.20240606`, `eng` and `osd`. Ignored `.env` now contains
the absolute `TESSERACT_CMD`; other settings were preserved. No global PATH or
registry-based OCR configuration is required.

Publisher installer SHA256:
`C885FFF6998E0608BA4BB8AB51436E1C6775C2BAFC2559A19B423E18678B60C9`, matching the
[Winget manifest](https://raw.githubusercontent.com/microsoft/winget-pkgs/master/manifests/u/UB-Mannheim/TesseractOCR/5.4.0.20240606/UB-Mannheim.TesseractOCR.installer.yaml).
Extraction tools/downloads were cleaned up. The working ignored
`.runtime/tesseract-portable/` remains installed.

### Exact successful setup and runtime commands

Run from the repository root. Local payload extraction used:

```powershell
New-Item -ItemType Directory -Force .runtime/downloads
Invoke-WebRequest https://github.com/ip7z/7zip/releases/download/26.06/7z2606-x64.msi -OutFile .runtime/downloads/7zip.msi
Invoke-WebRequest https://github.com/UB-Mannheim/tesseract/releases/download/v5.4.0.20240606/tesseract-ocr-w64-setup-5.4.0.20240606.exe -OutFile .runtime/downloads/tesseract-installer.exe
Get-FileHash -Algorithm SHA256 .runtime/downloads/tesseract-installer.exe
# Verify the exact publisher hash above before extraction.
$archiveTarget = Join-Path (Get-Location) '.runtime/7zip'
$archiveSource = Join-Path (Get-Location) '.runtime/downloads/7zip.msi'
Start-Process msiexec.exe -WindowStyle Hidden -Wait -ArgumentList @('/a', ('"' + $archiveSource + '"'), '/qn', ('TARGETDIR="' + $archiveTarget + '"'))
& '.runtime/7zip/Files/7-Zip/7z.exe' x .runtime/downloads/tesseract-installer.exe '-o.runtime/tesseract-portable' -y
& '.runtime/tesseract-portable/tesseract.exe' --version
& '.runtime/tesseract-portable/tesseract.exe' --list-langs
```

7-Zip emitted a PE-header warning but reported successful NSIS extraction. The exact
publisher hash and real executable/OCR checks verified the result. Configure the
absolute executable path as `TESSERACT_CMD` in ignored `.env`.
[7-Zip downloads](https://www.7-zip.org/download.html) and
[Microsoft administrative images](https://learn.microsoft.com/en-us/windows/win32/msi/administrative-installation)
describe the tools used; 7-Zip needed no machine-wide installation.

```powershell
.venv\Scripts\python -m pip install --only-binary=:all: grpcio==1.76.0 pybase64==1.4.2
.venv\Scripts\python -c "import grpc, pybase64, chromadb; print(grpc.__version__, pybase64.__version__, chromadb.__version__)"
# 1.76.0 1.4.2 1.5.9
.venv\Scripts\python -m backend.rag.ingest
# Ingested 43 chunks into existing data/chroma, collection corecare_medical.
.venv\Scripts\python -m scripts.verify_report_runtime --consent
# Current result: live_groq=verified, overall=verified_requested_checks; exit 0.
# An absent key still produces a nonzero result rather than a mocked success.
```

Ingest downloaded the existing MiniLM ONNX model and upserted the same collection
without reset. A direct CBC query returned the actual MedlinePlus CBC document with
score `0.7648`. The production isolated query used by the verifier returned the same
document with score `0.7056` (different query wording).

## Actual synthetic end-to-end results

The verifier used real Tesseract, Chroma/ONNX, production isolated workers and HTTP
multipart uploads to a temporary loopback-only Uvicorn server. No dependency
overrides, fake services or real patient records were used. The server stopped after
verification.

| Input | HTTP | Extraction | Comparison | Status |
|---|---|---|---|---|
| PNG | 200 | Three exact values, units and ranges | Indeterminate: OCR uncertainty | Partial, expected |
| Scanned PDF | 200 | Three exact values, units and ranges; page 1 | Indeterminate: OCR uncertainty | Partial, expected |
| Text PDF, explicit consent | 200 | Three exact values, units and ranges; page 1 | Below / above / within | Completed: live Groq and citations verified |

Synthetic rows: Hemoglobin `10.2 g/dL`, range `12-16`; WBC `13.0 K/uL`, range `4-11`;
platelets `250 K/uL`, range `150-400`. These are fixture ranges, not universal normal
values. Response schemas, original values, page attribution, record sources,
disclaimers and returned citation indices were validated. OCR uncertainty was not
removed to manufacture definitive comparisons.

The first image used a console font whose slashed zero was read as `@`. The parser
correctly marked `25@` unreadable rather than inventing a measurement. The final
fixture uses ordinary Arial report text; expected measurements and exact assertions
were unchanged. This illustrates the existing OCR limitation rather than robustness
to poor scans.

Ignored synthetic evidence:

- `reports/runtime/verification.json`: actual OCR version, HTTP results and retrieved documents.
- `reports/runtime/png_extraction.json`, `scanned_pdf_extraction.json`: real OCR text.
- `reports/runtime/png_response.json`, `scanned_pdf_response.json`, `text_pdf_response.json`.
- `reports/runtime/synthetic_cbc.png`, `synthetic_cbc_scanned.pdf`, `synthetic_cbc_text.pdf`.

## Live Groq failure diagnosis and fix

The API key was loaded without displaying it. The failed response had
`external_llm_used=true`, only a record source, and the misleading warning
`Reference retrieval unavailable`. Actual retrieval succeeded, with real CBC and
other corpus documents; the evidence IDs sent to Groq were `[2, 3]`, correctly
reserving `[1]` for the uploaded report.

The failures were traced in order rather than treating missing citations as proof
that retrieval or citation validation was broken:

1. **SDK/base-URL mismatch:** Groq SDK 1.7.0 includes `/openai/v1` in resource paths.
   The configured base also included that suffix, producing
   `/openai/v1/openai/v1/chat/completions`. Groq returned HTTP 404 `unknown_url`.
   The service now normalizes the legacy suffix before constructing the SDK client.
   The default/example URL is `https://api.groq.com`; old `.env` values remain valid.
2. **Unavailable model:** after correcting the URL, Groq returned HTTP 404
   `model_not_found` for `llama-3.3-70b-versatile`. An authenticated model listing
   confirmed accessible `openai/gpt-oss-20b`, now configured locally and by default.
   The key itself was preserved. No authentication or timeout failure was observed.
3. **Reasoning-token exhaustion:** the replacement model initially consumed the
   entire 1024-token budget, returned `finish_reason=length`, and produced no final
   content. GPT-OSS now receives documented low reasoning effort and excludes
   reasoning text from the response; the configured/default budget is 2048 tokens.
   Truncation raises the explicit `llm_token_limit` error rather than empty JSON.
4. **Misleading diagnostics:** unhandled API status errors previously fell into a
   generic handler labeled retrieval failure. They now become safe typed LLM errors
   with status/code; API failures and retrieval failures are distinguished. The
   verifier still asserts validated reference citations and now includes safe
   warning/source-type diagnostics if that assertion fails.
5. A full HTTP run then returned valid JSON with empty excerpts, not rejected or
   malformed citations. The prompt's blanket prohibition on numbers was ambiguous
   alongside mandatory numeric source IDs. It now explicitly requires numeric IDs,
   limits the prohibition to quote text, and supplies prefiltered `allowed_quotes`.
   Source IDs, verbatim sentence matching, medical safety, Pydantic validation and
   verifier citation assertions remain enforced. No fallback citations were invented.

Model availability was checked against the real authenticated API and
[Groq's model documentation](https://console.groq.com/docs/models).
The GPT-OSS effort setting follows
[Groq reasoning documentation](https://console.groq.com/docs/reasoning).
No model reasoning text was printed or stored during diagnosis; only completion
metadata, safe exception classes/codes, public evidence and final output were inspected.

### Verified final result

The real loopback HTTP verifier completed successfully with explicit consent:

- `groq_key_configured=true`, `external_llm_used=true`.
- Text-PDF response: `status=completed`, three correct tests/range comparisons,
  `warnings=[]`, two sources (record `[1]`, actual MedlinePlus CBC reference `[2]`).
- Five educational excerpts cited `[2]` and passed exact sentence/safety validation.
- The verifier checked citation indices and matched reference snippets/URLs to
  documents actually stored in the existing Chroma collection.
- PNG and scanned-PDF OCR checks passed; uncertainty remains indeterminate by design.
- `live_groq=verified`, `overall=verified_requested_checks`, verifier exit 0.

Current synthetic evidence is in ignored `reports/runtime/verification.json` and
`text_pdf_response.json`. No real patient data or API secrets were written there.

### Final commands and results

```powershell
.venv\Scripts\python -m pytest -q
# 148 passed in 3.72s (all original 137 plus 11 new regressions)
.venv\Scripts\python -m pytest tests/test_reports.py -q
# 100 original Week 4 tests passed
.venv\Scripts\python -m pytest tests/test_chat_api.py tests/test_patient_agent.py tests/test_orchestrator.py tests/test_router.py tests/test_main.py tests/test_session_store.py tests/test_schemas.py -q
# 37 original Week 2 tests passed
.venv\Scripts\python -m pytest tests/test_llm_service.py -q
# 11 new regression cases passed
.venv\Scripts\python -m scripts.verify_report_runtime --consent
# Exit 0: live_groq=verified; overall=verified_requested_checks
```

The new tests exercise the actual pinned SDK with an offline HTTP transport: root,
legacy and proxy URL construction; safe non-retryable 400/401/403/404 errors;
truncated reasoning responses; exact evidence IDs/quote candidates and validated
record/reference citations; and correct API-failure attribution. No original test
was removed, skipped or weakened.

## Remaining limitations

Model availability and provider quotas can change; failures remain explicit and do
not manufacture citations. Live verification establishes this synthetic workflow,
not clinical validity. The parser still excludes arbitrary layouts, imaging and
unit conversion. OCR readings remain uncertain; noisy/slashed-zero text can fail.
RSS monitoring can overshoot briefly, concurrency is per server process, and
production authentication/access controls remain deployment work. Research code,
Week 3/5 functionality and Windows security controls were not modified.
