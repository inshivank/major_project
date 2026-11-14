# CoreCare

**CoreCare: An LLM-Driven Multi-Agent Framework for Intelligent Healthcare Services**

A B.Tech major project that builds an application layer for LLM-powered healthcare
services on top of the open-source [ColaCare](https://github.com/PKU-AICare/ColaCare)
research framework.

> Medical safety notice: CoreCare is a research/educational project, **not** a medical
> diagnosis system. It is not a substitute for professional medical advice or care.

## Current Status (Week 2 — Online Phase Foundation)

The online path works end to end: request routing, Groq LLM service, ChromaDB medical
retrieval, and the Patient Assistance agent with safety guardrails.

| Capability | Status |
|---|---|
| `POST /chat` with session memory | Done |
| Groq LLM service (retries, JSON, typed errors) | Done |
| ChromaDB corpus ingest + retrieval | Done (12 sources, 37 chunks) |
| Intent router (rules first, LLM fallback) | Done |
| Agent 1: Patient Assistance (RAG + citations + guardrails) | Done |
| Agent 2: Medical Report Understanding (OCR) | Stub, Week 4 |
| Agent 3: Clinical Record Analysis (predictions) | Stub, Week 3+ |
| Phase 1 model training (AdaCare / MCGRU / RETAIN) | Not started |

## Architecture

```
Doctor -> POST /chat -> Orchestrator -> Router (rules -> LLM fallback)
                                            |
              +-----------------------------+-----------------------------+
              |                             |                             |
      Patient Assistance            Report Understanding          Clinical Record
      (Groq + RAG)                  (stub)                        (stub)
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

| Endpoint | Description |
|---|---|
| `GET /` | Health check |
| `GET /config` | Public model/retrieval config (no secrets) |
| `POST /chat` | Route a question to an agent |

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
- Week 3: Phase 1 models (AdaCare / MCGRU / RETAIN) + EHR record retrieval
- Week 4: Medical Report agent (upload, OCR, lab explanation)
- Week 5: Clinical Record agent (predictions with LLM explanation)
- Week 6: Multi-agent collaboration, fusion, evaluation, UI

See [`docs/plan-week2.md`](docs/plan-week2.md) for the detailed Week 2 plan.
