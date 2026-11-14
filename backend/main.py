"""FastAPI entrypoint for CoreCare."""

from functools import lru_cache

from fastapi import Depends, FastAPI, HTTPException

from backend.config.settings import settings
from backend.llm.llm_service import LLMError
from backend.orchestrator.orchestrator import Orchestrator
from backend.schemas.chat import ChatRequest, ChatResponse

app = FastAPI(title="CoreCare", version="0.2.0")


@lru_cache
def get_orchestrator() -> Orchestrator:
    return Orchestrator.build_default()


@app.get("/")
async def health_check():
    return {"message": "CoreCare API is running"}


@app.get("/config")
async def public_config():
    return {
        "llm_model": settings.llm_model,
        "llm_configured": bool(settings.groq_api_key),
        "retrieval_top_k": settings.retrieval_top_k,
    }


@app.post("/chat", response_model=ChatResponse)
async def chat(
    request: ChatRequest,
    orchestrator: Orchestrator = Depends(get_orchestrator),
) -> ChatResponse:
    try:
        return orchestrator.chat(request)
    except LLMError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
