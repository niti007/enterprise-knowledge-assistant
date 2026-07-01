"""
app/main.py
===========
FastAPI application for the Enterprise Knowledge Assistant.

Endpoints:
    GET  /health        — service health check
    POST /chat          — RAG-powered Q&A with citations

Run:
    uvicorn app.main:app --host 0.0.0.0 --port 8001 --reload
"""
from __future__ import annotations

import time
import uuid
from typing import Any

import structlog
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

log = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Enterprise Knowledge Assistant",
    description="Hybrid RAG (vector + graph) knowledge assistant with citations and tracing.",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # restrict in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Startup / settings validation
# ---------------------------------------------------------------------------

@app.on_event("startup")
async def startup_event() -> None:
    """Validate config on startup — fail loud if required vars missing."""
    from app.config import get_settings  # noqa: F401 — triggers validation

    settings = get_settings()
    log.info(
        "startup",
        env=settings.app_env,
        model=settings.llm_default_model,
        chroma_dir=str(settings.chroma_persist_path),
        langfuse_enabled=settings.langfuse_enabled,
    )


# ---------------------------------------------------------------------------
# In-memory session store (replace with Redis in Phase 2)
# ---------------------------------------------------------------------------

_sessions: dict[str, list[dict[str, Any]]] = {}


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------

class ChatRequest(BaseModel):
    session_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    message: str = Field(..., min_length=1, max_length=4096, description="User query")
    top_k: int = Field(default=5, ge=1, le=20, description="Number of chunks to retrieve")


class CitationModel(BaseModel):
    source: str
    doc_type: str
    dept: str
    score: float
    rank: int
    snippet: str


class ChatResponse(BaseModel):
    session_id: str
    answer: str
    citations: list[CitationModel]
    trace_id: str
    latency_ms: float
    model: str
    chunks_retrieved: int
    # Phase 2 additions (additive — existing clients ignore unknown fields)
    cache_hit: bool = False
    cache_similarity: float | None = None
    model_used: str = ""
    guardrail_flags: list[str] = Field(default_factory=list)
    guardrail_reasons: list[str] = Field(default_factory=list)
    tool_calls: list[dict[str, Any]] = Field(default_factory=list)
    blocked: bool = False
    blocked_reason: str | None = None


class HealthResponse(BaseModel):
    status: str
    version: str
    uptime_s: float
    chroma_count: int | None = None


_start_time = time.perf_counter()


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/health", response_model=HealthResponse, tags=["infra"])
async def health() -> HealthResponse:
    """
    Service health check.
    Also probes ChromaDB to report index size.
    """
    chroma_count: int | None = None
    try:
        from app.ingestion.chunker import get_chroma_collection

        collection = get_chroma_collection()
        chroma_count = collection.count()
    except Exception:
        pass  # don't fail health if chroma is empty

    return HealthResponse(
        status="ok",
        version="1.0.0",
        uptime_s=round(time.perf_counter() - _start_time, 1),
        chroma_count=chroma_count,
    )


@app.post("/chat", response_model=ChatResponse, tags=["chat"])
async def chat(request: ChatRequest) -> ChatResponse:
    """
    RAG-powered Q&A endpoint.

    Retrieves relevant context from ChromaDB, generates an answer via OpenAI,
    and returns the answer with citations and a Langfuse trace_id.
    """
    if not request.message.strip():
        raise HTTPException(status_code=400, detail="message cannot be empty")

    # Maintain session history (unused by pipeline in Phase 1, but stored)
    if request.session_id not in _sessions:
        _sessions[request.session_id] = []
    _sessions[request.session_id].append({"role": "user", "content": request.message})

    try:
        from app.pipeline import get_pipeline

        pipeline = get_pipeline()
        result = pipeline.run(
            message=request.message,
            session_id=request.session_id,
            top_k=request.top_k,
        )
    except RuntimeError as exc:
        # Friendly error for common setup problems (empty index, etc.)
        raise HTTPException(status_code=503, detail=str(exc))
    except Exception as exc:
        log.error("pipeline_error", error=str(exc))
        raise HTTPException(status_code=500, detail=f"Pipeline error: {exc}")

    _sessions[request.session_id].append(
        {"role": "assistant", "content": result["answer"]}
    )

    return ChatResponse(
        session_id=request.session_id,
        answer=result["answer"],
        citations=[CitationModel(**c) for c in result["citations"]],
        trace_id=result["trace_id"],
        latency_ms=result["latency_ms"],
        model=result["model"],
        chunks_retrieved=result["chunks_retrieved"],
        cache_hit=result.get("cache_hit", False),
        cache_similarity=result.get("cache_similarity"),
        model_used=result.get("model_used", result["model"]),
        guardrail_flags=result.get("guardrail_flags", []),
        guardrail_reasons=result.get("guardrail_reasons", []),
        tool_calls=result.get("tool_calls", []),
        blocked=result.get("blocked", False),
        blocked_reason=result.get("blocked_reason"),
    )


@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    log.error("unhandled_error", path=request.url.path, error=str(exc))
    return JSONResponse(status_code=500, content={"detail": str(exc)})
