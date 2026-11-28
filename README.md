

**CoreCare: An LLM-Driven Multi-Agent Framework for Intelligent Healthcare Services**

A B.Tech major project that builds an application layer for LLM-powered healthcare
services on top of the open-source [ColaCare](https://github.com/PKU-AICare/ColaCare)
research framework.

> Medical safety notice: CoreCare is a research/educational project, **not** a medical
> diagnosis system. It is not a substitute for professional medical advice or care.

## Current Status (Weeks 4–5 — Report and Clinical Record Agents)

The online path works end to end: request routing, Groq LLM service, ChromaDB medical
retrieval, and the Patient Assistance agent with safety guardrails.

| Capability | Status |
|---|---|
| `POST /chat` with session memory | Done |
| Groq LLM service (retries, JSON, typed errors) | Done |
| ChromaDB corpus ingest + retrieval | Runtime verified (18 documents, 43 chunks) |
| Intent router (rules first, LLM fallback) | Done |
| Agent 1: Patient Assistance (RAG + citations + guardrails) | Done |
| Agent 2: Medical Report Analysis | Upload, local extraction/OCR, ranges, consent-gated RAG explanation |
| Agent 3: Clinical Record Analysis (predictions) | Done (local EHR lookup, model scores, consent-gated explanation) |
| Phase 1 model training (AdaCare / MCGRU / RETAIN) | Done (6 models on MIMIC-IV demo; full dataset pending) |

## Architecture

```
Doctor -> POST /chat -> Orchestrator -> Router (rules -> LLM fallback)
                                            |
              +-----------------------------+-----------------------------+
              |                             |                             |
      Patient Assistance            Report Understanding          Clinical Record
      (Groq + RAG)                  (upload endpoint)             (EHR + model scores)
              |                             |                             |
              +-----------------------------+-----------------------------+
                                            |
                    Merge answer + sources -> structured response
```

Every response carries `sources[]` labelled `reference`, `record`, or `model`, so the
UI can show what came from guidelines, the patient record, or a trained model.

## Repository Layout

```
CoreCare/
|
+-- backend/
|   +-- main.py              # FastAPI entrypoint, POST /chat
|   +-- agents/              # Agent implementations + prompts
|   +-- orchestrator/        # Router, dispatch, session memory
|   +-- rag/                 # Corpus ingest CLI + ChromaDB retriever
|   +-- llm/                 # Groq service layer
|   +-- schemas/             # API contracts
|   +-- config/              # Environment-backed settings
|
+-- data/
|   +-- corpus/              # Seed medical references (+ SOURCES.md)
|   +-- chroma/              # Generated vector store (git-ignored)
|
+-- research/
|   +-- colacare/            # Original ColaCare repo (READ-ONLY)
|
+-- scripts/                 # Evaluation helpers
+-- docs/                    # Plans and design notes
+-- tests/                   # Offline test suite
+-- requirements.txt
+-- README.md
```

`research/colacare/` is a clone of the original ColaCare project. It is treated as
**read-only** and must not be modified, deleted, or rewritten.

## Setup

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

Create `.env` from the template and add your Groq key
(from <https://console.groq.com/keys>):

```powershell
Copy-Item .env.example .env
# edit .env -> GROQ_API_KEY=gsk_...
```

`.env` is git-ignored. Never commit a key.

## Build the retrieval store

```powershell
.venv\Scripts\python -m backend.rag.ingest --reset
```

The first run downloads the ChromaDB ONNX embedding model (~80 MB) into
`~/.cache/chroma`. Re-runs are incremental and idempotent.

## Running the server

```powershell
.venv\Scripts\python -m uvicorn backend.main:app --reload
```

Or use the launcher, which starts the server and opens the selected popup:

```powershell
.venv\Scripts\python run_agents.py
corecare> agent1
corecare> agent3
```

Direct form: `.venv\Scripts\python run_agents.py agent1`

| Endpoint | Description |
|---|---|
| `GET /` | Health check |
| `GET /config` | Public model/retrieval config (no secrets) |
| `GET /assistant` | Pop-up patient guidance UI backed by `/chat` |
| `GET /demo` | Pop-up patient search UI backed by `/chat` |
| `POST /chat` | Route a question to an agent (`patient_id`, `external_llm_consent` optional) |
| `POST /reports/analyze` | Multipart medical PDF/image analysis |

Example:

```powershell
$body = @{ message = "What are the warning signs of a stroke?" } | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/chat `
  -ContentType "application/json" -Body $body
```

Response shape:

```json
{
  "answer": "... [1][2]",
  "sources": [
    { "type": "reference", "title": "Stroke: recognising and acting fast",
      "url": "https://www.stroke.org/...", "score": 0.61 }
  ],
  "agent": "patient_agent",
  "intent": "general_question",
  "status": "ok",
  "session_id": "…",
  "disclaimer": "This is AI-generated decision support ..."
}
```

Send `session_id` back to keep conversation context. Emergency messages short-circuit
the LLM and return immediate advice to contact local emergency services. Diagnosis and
prescription requests are refused deterministically.

For Agent 3, send `patient_id` (a `RecordID` from `data/processed/mimic_demo_formatted.csv`,
or a `PatientID` that maps to one). Risk scores come from `predictions/*.pkl`. Local EHR
and model sources are always returned; set `external_llm_consent=true` to allow Groq to
explain only the task names, risk bands, and retrieved references — never the patient ID
or raw record values.

```powershell
$body = @{
  message = "Predict mortality and readmission risk for this record"
  patient_id = "10001217_34592300"
  external_llm_consent = $true
} | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/chat `
  -ContentType "application/json" -Body $body
```

## Tests

```powershell
.venv\Scripts\python -m pytest
```

All tests are offline: the Groq client and retriever are replaced with fakes, so no API
key or network is needed.

Optional smoke checks:

```powershell
.venv\Scripts\python -m scripts.eval_patient_agent --offline  # retrieval coverage
.venv\Scripts\python -m scripts.eval_patient_agent --live     # writes reports/*.csv
```

## Dependencies

- [fastapi](https://fastapi.tiangolo.com/) / [uvicorn](https://www.uvicorn.org/) — API
- [pydantic](https://docs.pydantic.dev/) / [pydantic-settings](https://docs.pydantic.dev/latest/concepts/pydantic_settings/) — validation and config
- [groq](https://console.groq.com/docs) — LLM inference (OpenAI-compatible)
- [chromadb](https://www.trychroma.com/) — vector store + local embeddings
- [python-dotenv](https://github.com/theskumar/python-dotenv) — `.env` loading

> Groq is the inference provider. xAI's Grok is a different product; switching would
> only require changing `GROQ_BASE_URL` and `LLM_MODEL`.

## Roadmap

- Week 1: Foundation (FastAPI skeleton, tests, repo layout) — done
- Week 2: Online phase foundation: Groq, RAG, Agent 1, orchestrator, `/chat` — done
- Week 3: Phase 1 models (AdaCare / MCGRU / RETAIN) + EHR record retrieval — done on demo
- Week 4: Medical Report agent (upload, OCR, lab explanation) — implemented; runtime setup below
- Week 5: Clinical Record agent (predictions with LLM explanation) — done
- Week 6: Multi-agent collaboration, fusion, evaluation, UI

## Medical Report Agent

The report path is independent of EHR retrieval and clinical ML:

```text
POST /reports/analyze (multipart)
 -> request/content/size validation
 -> isolated PDF text extraction or Tesseract OCR (page attribution)
 -> deterministic laboratory parser + Pydantic validation
 -> deterministic comparisons against the report's own ranges
 -> optional existing Chroma retrieval + existing Groq JSON service
 -> validated educational excerpts + numbered record/reference sources
```

PDFs with selectable text, scanned PDFs, PNG and JPEG are supported. Common CBC,
glucose/HbA1c, lipid, liver, kidney and thyroid labels are recognized. Original
measurement strings and units are retained. Reference ranges are never invented;
missing units, qualified values, incompatible range units and ambiguous ranges
produce `indeterminate`. OCR results always carry uncertainty and require human
verification before range comparisons can be trusted.

### Setup and use

Install the updated `requirements.txt`. Text PDFs need no OCR executable. For scans,
install Tesseract separately, including English language data. On Windows:

```powershell
winget install --id UB-Mannheim.TesseractOCR --exact
# If it is not on PATH, set in .env:
# TESSERACT_CMD=C:/Program Files/Tesseract-OCR/tesseract.exe
```

On Debian/Ubuntu, the runtime package is `tesseract-ocr`. PDF rasterization uses
PyMuPDF directly; Poppler is not required. Restart the server after changing `.env`.
Re-run the existing ingest command to add `data/corpus/lab_tests.json` to the same
Chroma collection. The six new educational summaries link to MedlinePlus; source
attribution is recorded in `data/corpus/SOURCES.md`.

```powershell
.venv\Scripts\python -m backend.rag.ingest
# Local processing only; no report information is sent to Groq:
curl.exe -X POST http://127.0.0.1:8000/reports/analyze -F "file=@synthetic-report.pdf"
# Explicit consent to send canonical test names and comparison statuses to Groq:
curl.exe -X POST http://127.0.0.1:8000/reports/analyze -F "file=@synthetic-report.pdf" -F "external_llm_consent=true"
```

Only use synthetic reports for demonstrations. Consent defaults to false and cannot
be bypassed by environment configuration. Even with consent, the application sends
only canonical test names and comparison statuses, plus retrieved reference evidence.
It does not send values, units, original labels, page text, filenames, patient
identifiers, or chat history. No consent means no report retrieval or Groq call.

The response includes `agent: medical_report`, `status: completed|partial`, report
type, page metadata, `tests[]`, summary, warnings, `external_llm_used`, disclaimer
and `sources[]`. Each test has `source_type: record`; source objects preserve the
existing `type: record|reference` convention. Citations `[n]` address `sources[n-1]`
in stable order. Local facts are rendered deterministically. Groq selects exact,
complete educational sentences from retrieved evidence; validation rejects invented
citations, altered excerpts, numerical medical claims and treatment instructions.
The result includes limitations and questions to discuss with a clinician.

`partial` means extraction, parsing, comparison or educational explanation was
incomplete, uncertain or unavailable (including absent external consent). Read the
warnings rather than interpreting this status as a clinical assessment. Errors use
`detail: {code, message}` with 413 for limits, 415 for unsupported content, 422 for
invalid/unreadable content, 408/504 for timeouts, 429 for capacity, and 503 for a
missing OCR runtime. `/docs` documents the multipart request.

### Privacy, limits and known limitations

Uploads are stateless. `/chat` report requests return upload instructions (or immediate emergency guidance) and store
only neutral guidance placeholders. Recognized pasted laboratory measurements route
locally without LLM intent classification. General questions about a test retain
the existing patient-education route. No report-reference cache or automatic reuse of
past results is implemented. Existing general, record and prediction routing remains
unchanged; the clinical agent remains unavailable.

Raw files are not retained. Multipart spools are closed on success/failure. Each
native worker uses a private temporary directory, removed after exit; OCR child
processes are terminated during timeout cleanup. Defaults: 10 MiB per file, ten PDF
pages, twenty million image pixels, one hundred thousand extracted characters,
thirty seconds for upload, fifteen seconds per OCR operation, and a shared
one-hundred-twenty-second processing deadline. Two report jobs are admitted per
server process. Worker-tree RSS is sampled against a configurable 512 MiB limit;
this is a monitored limit, not an OS-enforced allocation quota. Brief overshoot is
possible. These bounds do not replace deployment resource limits.

Encrypted (including empty-password), repaired, active-content and attachment-bearing
PDFs are rejected. Limits and `TESSERACT_CMD` are configured through `.env.example`.
No application logs contain report bodies or filenames; shared LLM retry logs record
exception types rather than provider messages.

The parser supports conventional label/value/unit/range rows, including same-row PDF
table cells, simple inequalities and repeated tests. It does not reconstruct arbitrary
multi-column layouts, infer demographics/dates/specimens, convert units, repair OCR
measurements, interpret imaging findings, or infer missing ranges. Unknown rows are
not explained. OCR works best with clear English scans; EXIF orientation and
confident Tesseract orientation detection are supported. Handwriting and poor scans
may fail. Ambiguity is preserved instead of using unconstrained LLM parsing.

A normal result does not guarantee health; an abnormal result is not a diagnosis.
The agent does not prescribe, calculate critical thresholds, or provide clinical
triage. It advises professional review and directs emergencies to local emergency
services. Authentication and user access controls remain deployment work inherited
from Week 2; do not expose this research API to real patient traffic without them.

### Verification

```powershell
.venv\Scripts\python -m pytest -q
.venv\Scripts\python -m pytest tests/test_reports.py -q
```

Tests use synthetic documents, real PDF/image processing, deterministic fake OCR,
fake retrieval and fake Groq transports. They require no external network or API key.
The fake transport tests exercise the existing service's JSON repair and deadlines.
Real OCR and live Groq/Chroma smoke checks are separate runtime checks; the offline
suite does not establish their availability. See `WEEK4_IMPLEMENTATION_REPORT.md`
for results and environment blockers observed during implementation.


Windows runtime verification on 2026-11-14 confirmed real OCR with Tesseract
`5.4.0.20240606`, synthetic uploads over loopback HTTP, and actual Chroma retrieval.
The working executable is `.runtime/tesseract-portable/tesseract.exe`; ignored
`.env` configures its absolute path. No global PATH or Windows security settings
were changed. Windows-only pins `grpcio==1.76.0` and `pybase64==1.4.2` satisfy
Chroma's dependencies and avoid builds blocked by this machine's policy.
Other managed machines may make different policy decisions.

```powershell
.venv\Scripts\python -m scripts.verify_report_runtime --consent
```

This starts/stops a real loopback-only Uvicorn server and verifies generated synthetic
PNG/scanned-PDF/text-PDF uploads, original measurements/ranges, production isolated
retrieval, response schemas and citation indices. Evidence is saved under ignored
`reports/runtime/`. No fake OCR, database or LLM is used. With no Groq key configured,
local checks pass but the command returns nonzero with `blocked_missing_key`; a live
explanation and external citations remain unverified. Configure a key locally before
explicitly rerunning with consent; never paste it into chat. The implementation
report records the working portable installation and exact verification commands.


Live Groq verification now passes with `openai/gpt-oss-20b`. The Groq SDK base URL
is the origin `https://api.groq.com`; legacy URLs ending in `/openai/v1` are
normalized because the pinned SDK already supplies that path. Defaults use a
2048-token budget and low GPT-OSS reasoning effort. Existing `.env` overrides take
precedence, so an unavailable old model must also be updated locally. The synthetic
verifier returned a completed consented response with validated record/reference
citations; all 148 offline tests pass. See the implementation report for the original
failure trace and the fixes. Missing keys or invalid citations still fail verification.
