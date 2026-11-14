# Week 2 Plan — Online Phase Foundation

## Context

Week 1 delivered only the foundation commit (`9d798fb`): FastAPI health endpoint, empty
module placeholders, pytest setup, and the read-only ColaCare research clone.

The project has two phases:

- **Phase 1 (offline):** preprocess MIMIC-IV / CDSL / ESRD, train and evaluate AdaCare,
  MCGRU, RETAIN, save best checkpoints.
- **Phase 2 (online):** doctor asks a question -> orchestrator routes to Patient
  Assistance / Medical Report Understanding / Clinical Record Analysis agents ->
  merged, source-attributed answer.

**Week 2 builds the Phase 2 backbone**: config, Groq LLM service, ChromaDB RAG,
Agent 1 (Patient Assistance) end-to-end, orchestrator + router scaffolding, `/chat` API,
and tests. Phase 1 code starts in Week 3; only long-lead access tasks start now.

> Naming note: **Groq** is the inference provider selected for the LLM service (hosts
> open-weight Llama/Qwen models through an OpenAI-compatible API). **Grok** is xAI's
> model and a different product. This plan targets Groq; switching later means changing
> only `base_url` + model name in `.env`.

## Scope

### In scope

- `backend/config/settings.py` — pydantic-settings, `.env` driven
- `backend/llm/llm_service.py` — Groq client, retries, timeouts, JSON helper
- `backend/rag/` — ChromaDB ingest CLI + retriever
- `backend/agents/patient_agent.py` — Agent 1 with RAG grounding + guardrails
- `backend/orchestrator/` — intent router + result merger, Agents 2/3 as registered stubs
- `backend/schemas/` — request/response contracts for `/chat`
- `backend/main.py` — `POST /chat`, session memory
- `tests/` — offline suite (mocked LLM)
- README + this plan kept current

### Out of scope (later weeks)

- Phase 1 dataset preprocessing, model training, checkpoint loading
- Agent 2 OCR / report parsing
- Agent 3 real model inference
- Multi-agent debate / critique loops (ColaCare-style)
- Streaming responses, persistence (DB), auth

## Target architecture (end of Week 2)

```
POST /chat {message, session_id?, patient_id?}
  |
  v
Orchestrator -> Router (rules first, LLM fallback)
  |            intent: general_question | record_query | report_explanation | prediction
  |
  +--> PatientAgent  (Groq + RAG)            IMPLEMENTED
  +--> ReportAgent   (stub: not_available)  WEEK 4
  +--> ClinicalAgent (stub: not_available)  WEEK 3+
  |
  v
Merger -> {answer, sources[], agent, disclaimer, session_id}
```

`sources` entries carry `type: "reference" | "record" | "model"` so the final UI can
show what came from guidelines, the patient record, or a trained model.

## Dependencies to add

```
pydantic-settings==2.16.3
groq==1.7.0
chromadb==1.5.9
```

`chromadb` pulls `onnxruntime`; use its built-in all-MiniLM-L6-v2 ONNX embedding
function so no PyTorch is needed. Re-pin exact versions after first install if
transitive resolution differs.

## Daily tasks

### Day 1 — Config, contracts, dependencies ✅/⬜

- [x] Add the three dependencies to `requirements.txt` and install into `.venv`
- [x] `backend/config/settings.py`: `GroqSettings` via `BaseSettings` with
      `groq_api_key`, `llm_model` (default `llama-3.3-70b-versatile`),
      `llm_temperature`, `llm_max_tokens`, `chroma_dir`, `corpus_dir`,
      `retrieval_top_k`, `embedding_model`
- [x] `.env.example` (key names only, no secrets); confirm `.env` is already ignored
- [x] `backend/schemas/chat.py`: `ChatRequest`, `Source`, `ChatResponse`
- [x] App must import and start with **no API key set** (fail at request time, not import)

**Accept:** `uvicorn backend.main:app` boots; `GET /` still returns the existing message.

### Day 2 — LLM service ✅/⬜

- [x] `backend/llm/llm_service.py`: thin Groq wrapper
      - `complete(messages, temperature, max_tokens) -> str`
      - `complete_json(messages, schema_hint) -> dict` (parse + repair + one retry)
      - timeout (e.g. 30 s), exponential backoff on 429/5xx, max 3 attempts
      - log model, latency, token usage; never log the API key
- [x] Raise a typed `LLMError` instead of leaking SDK exceptions

**Accept:** mocked-transport test returns text and JSON; retry path covered once.

### Day 3 — RAG over ChromaDB ✅/⬜

- [x] `backend/rag/ingest.py` CLI: load `.md/.txt/.json` -> chunk (approx. 800 chars,
      100 overlap, paragraph-aware) -> upsert into a persistent Chroma collection with
      metadata `{title, source, url}`
- [x] `backend/rag/retriever.py`: `retrieve(query, k) -> list[RetrievedChunk]`
      (`text`, `source`, `url`, `score`); idempotent re-ingest (`stable ids = hash`)
- [x] Seed `data/corpus/` with 10-20 curated public sources (WHO, NHS, MedlinePlus,
      CDC) plus `data/corpus/SOURCES.md` recording title/URL/licence per file
- [x] `.gitignore`: Chroma persist dir (e.g. `data/chroma/`)

**Accept:** `python -m backend.rag.ingest` builds the store; a query for
"type 2 diabetes symptoms" returns on-topic chunks with sources.

### Day 4 — Agent 1: Patient Assistance ✅/⬜

- [x] `backend/agents/base.py`: `AgentResult`, `Agent` protocol
      (`can_handle(intent)`, `handle(query, context)`)
- [x] `backend/agents/patient_agent.py`
      - retrieve top-k, inject as numbered context with source tags
      - reply must cite `[1]`, `[2]` and map citations into `sources`
      - guardrails: refuse diagnosis/prescription/lab interpretation as definitive,
        route emergencies to local emergency services, always append
        "decision support, not a diagnosis"
      - conversation history limited to last N turns from the session store
- [x] Prompts live in `backend/agents/prompts/patient_agent.md` (patient/doctor-facing,
      adapted from `research/colacare/utils/prompt_template/`; do not modify the clone)

**Accept:** grounded answer with citations; diagnosis request refused;
emergency message triggers the safety response.

### Day 5 — Orchestrator, router, `/chat` ✅/⬜

- [x] `backend/orchestrator/router.py`: classify intent with keyword/rule table first,
      LLM classification fallback; intents `general_question`, `record_query`,
      `report_explanation`, `prediction`
- [x] `backend/orchestrator/orchestrator.py`: dispatch -> collect `AgentResult`s ->
      merge answer + dedupe sources; unknown/unsupported intent returns a clear message
- [x] Register stubs for Report/Clinical agents that return `status: "not_available"`
      with the planned week — no crashes, no fake predictions
- [x] `backend/main.py`: `POST /chat` using the Day 1 schemas; in-memory session store
      keyed by `session_id` (bounded, e.g. 50 turns / 20 sessions); 422 on empty message

**Accept:** four representative prompts route to the expected intent;
`/chat` returns the structured response end-to-end; stubs degrade gracefully.

### Day 6 — Tests and smoke eval ✅/⬜

- [x] `tests/`: fake `LLMService` and fake retriever fixtures (no network)
      - schemas validation, router routing, orchestrator merge/dedupe
      - guardrail tests (diagnosis refusal, emergency branch)
      - `/chat` 200, 422, unknown-intent, stub-agent responses
- [x] Keep the existing `tests/test_main.py` health test green
- [x] `scripts/eval_patient_agent.py`: 20-question smoke set with a manual
      relevance/groundedness score sheet

**Accept:** `pytest` passes offline; eval script runs against a saved transcript mode.

### Day 7 — Docs, demo, commit ✅/⬜

- [x] README: Groq key, ingest step, run commands, `/chat` request/response example,
      architecture diagram, safety notice
- [x] Demo with `Invoke-RestMethod` (PowerShell)
- [x] Commit on a `week2-online-foundation` branch in logical commits

## Definition of done

- `pip install -r requirements.txt` succeeds in a clean venv from Python 3.11
- `POST /chat` returns a RAG-grounded, cited answer through the orchestrator
- Refuses diagnosis/prescription and routes emergencies
- `pytest` green offline; no test needs a real Groq key
- `research/colacare/` byte-identical to the clone (verify with `git status`)
- README documents setup, ingest, and the API

## Risks and mitigations

| Risk | Mitigation |
|---|---|
| Groq rate limits / model deprecation | model name in `.env`; backoff + clear error; fallback model configurable |
| First-run ONNX embedding download (~80 MB) | download during ingest, document offline step, cache under `data/` |
| Chroma version churn | pin exact version; persist dir git-ignored; ingest is idempotent |
| Medical inaccuracy / liability | curated sources only, mandatory citations, disclaimer, no diagnosis |
| Corpus licensing | record licence per source in `SOURCES.md`; prefer public-domain sources |
| Scope creep from Phase 1 | Phase 1 code starts Week 3; only access paperwork now |

## Long-lead Phase 1 actions (start this week, no code)

- [x] Create PhysioNet account; complete CITI "Data or Specimens Only Research" training
- [x] Submit MIMIC-IV (and MIMIC-IV-ED if needed) credentialing + DUA — typically
      1-2 weeks turnaround; blocks Week 3+
- [x] Confirm access to CDSL and ESRD; note licences and download sizes
- [x] Decide model compute target (local GPU vs Colab/cloud) before training week
- [x] Reuse `research/colacare/pyehr/models/` (AdaCare, MCGRU, RETAIN) by import/copy;
      do not rewrite or modify the clone
