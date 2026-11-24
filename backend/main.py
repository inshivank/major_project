"""FastAPI entrypoint for CoreCare."""

from functools import lru_cache

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool
from threading import BoundedSemaphore
from backend.agents.report_agent import ReportAgent
from backend.reports.errors import ReportError
from backend.reports.upload import ReportUploadLimit, read_upload
from backend.schemas.report import ReportResponse

from backend.config.settings import settings
from backend.llm.llm_service import LLMError
from backend.orchestrator.orchestrator import Orchestrator
from backend.schemas.chat import ChatRequest, ChatResponse, Intent

app = FastAPI(title="CoreCare", version="0.4.0")
app.add_middleware(ReportUploadLimit)
report_slots = BoundedSemaphore(settings.report_max_concurrent)


@app.exception_handler(ReportError)
async def report_error_handler(request, exc):
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": {"code": exc.code, "message": str(exc)}},
    )


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


def get_report_agent(
    orchestrator: Orchestrator = Depends(get_orchestrator),
) -> ReportAgent:
    return orchestrator._select_agent(Intent.REPORT_EXPLANATION)


@app.post(
    "/reports/analyze",
    response_model=ReportResponse,
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                "multipart/form-data": {
                    "schema": {
                        "type": "object",
                        "required": ["file"],
                        "properties": {
                            "file": {"type": "string", "format": "binary"},
                            "external_llm_consent": {
                                "type": "boolean",
                                "default": False,
                                "description": "Consent to sending canonical test names and comparison statuses to Groq. Raw text and identifiers are never sent.",
                            },
                        },
                    }
                }
            },
        }
    },
)
async def analyze_report(
    request: Request, agent: ReportAgent = Depends(get_report_agent)
):
    # Parse explicitly to bound field/file count; request middleware bounds total bytes.
    if not report_slots.acquire(blocking=False):
        raise ReportError("report_busy", "Report processing is busy; retry later.", 429)
    try:
        data, consent = await read_upload(request)
        return await run_in_threadpool(agent.analyze, data, consent=consent)
    finally:
        report_slots.release()
