# CoreCare

**CoreCare: An LLM-Driven Multi-Agent Framework for Intelligent Healthcare Services**

A B.Tech major project that builds an application layer for LLM-powered healthcare
services on top of the open-source [ColaCare](https://github.com/PKU-AICare/ColaCare)
research framework.

> Medical safety notice: CoreCare is a research/educational project, **not** a medical
> diagnosis system. It is not a substitute for professional medical advice or care.

## Current Status (Foundation)

This is the foundation step of Week 1. No AI functionality is implemented yet.

## Repository Layout

```
CoreCare/
│
├── backend/                 # CoreCare application backend
│   ├── main.py              # FastAPI entrypoint (placeholder)
│   ├── agents/              # Agent implementations (placeholder)
│   ├── rag/                 # Retrieval-augmented generation (placeholder)
│   ├── llm/                 # LLM service layer (placeholder)
│   └── config/              # Environment-based configuration (placeholder)
│
├── research/
│   └── colacare/            # Original ColaCare research repo (READ-ONLY)
│                            # https://github.com/PKU-AICare/ColaCare
│
├── tests/                   # Test suite
├── requirements.txt         # Python dependencies
└── README.md
```

`research/colacare/` is a clone of the original ColaCare project. It is treated as
**read-only** and must not be modified, deleted, or rewritten.

## Setup

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

## Running the server

```powershell
.venv\Scripts\activate
uvicorn backend.main:app --reload
```

The API will be available at `http://127.0.0.1:8000`. Verify with:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/
```

## Dependencies

- [fastapi](https://fastapi.tiangolo.com/) — API framework
- [uvicorn](https://www.uvicorn.org/) — ASGI server
- [pydantic](https://docs.pydantic.dev/) — data validation
- [python-dotenv](https://github.com/theskumar/python-dotenv) — environment loading

## Planned Roadmap

- Week 1: Patient Assistance Agent (RAG + LLM + FastAPI chat endpoint)
- Later: Appointment Agent, Medical Report Agent, multi-agent collaboration,
  ColaCare pipeline integration