"""
app/observability/tracing.py — Langfuse tracing wrappers.

Usage:
    from app.observability.tracing import get_tracer, trace_pipeline_step

    tracer = get_tracer()
    with tracer.trace("pipeline", session_id=sid, user_id="anon") as root:
        with tracer.span(root, "retrieval") as span:
            # ... do retrieval ...
            tracer.end_span(span, output={"chunks": n}, metadata={"top_k": k})
"""
from __future__ import annotations

import time
import uuid
from contextlib import contextmanager
from typing import Any, Generator

import structlog

log = structlog.get_logger(__name__)


class _NoopSpan:
    """Dropped-in when Langfuse is disabled — zero overhead."""

    def __init__(self, name: str = "noop"):
        self.id = str(uuid.uuid4())
        self.name = name
        self._start = time.perf_counter()

    @property
    def trace_id(self) -> str:
        return self.id

    def update(self, **_: Any) -> None:
        pass

    def end(self, **_: Any) -> None:
        pass


class Tracer:
    """Thin wrapper around Langfuse that degrades to no-ops when disabled."""

    def __init__(self, enabled: bool, public_key: str, secret_key: str, host: str):
        self._enabled = enabled
        self._lf = None
        if enabled:
            try:
                from langfuse import Langfuse  # type: ignore

                self._lf = Langfuse(
                    public_key=public_key,
                    secret_key=secret_key,
                    host=host,
                )
                log.info("Langfuse tracing enabled", host=host)
            except Exception as exc:
                log.warning("Langfuse init failed — tracing disabled", error=str(exc))
                self._enabled = False

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @contextmanager
    def trace(
        self,
        name: str,
        session_id: str | None = None,
        user_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Generator[Any, None, None]:
        """Context manager that wraps an entire pipeline run as a Langfuse trace."""
        if not self._enabled or self._lf is None:
            span = _NoopSpan(name)
            yield span
            return

        trace_obj = self._lf.trace(
            name=name,
            session_id=session_id,
            user_id=user_id or "anonymous",
            metadata=metadata or {},
        )
        try:
            yield trace_obj
        finally:
            try:
                self._lf.flush()
            except Exception:
                pass

    @contextmanager
    def span(
        self,
        parent: Any,
        name: str,
        input: Any = None,
        metadata: dict[str, Any] | None = None,
    ) -> Generator[Any, None, None]:
        """Context manager for a sub-span within a trace."""
        if not self._enabled or self._lf is None:
            yield _NoopSpan(name)
            return

        span_obj = parent.span(name=name, input=input, metadata=metadata or {})
        start = time.perf_counter()
        try:
            yield span_obj
        finally:
            latency_ms = (time.perf_counter() - start) * 1000
            try:
                span_obj.end(metadata={"latency_ms": latency_ms})
            except Exception:
                pass

    def log_generation(
        self,
        parent: Any,
        name: str,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
        input_text: str = "",
        output_text: str = "",
    ) -> None:
        """Record an LLM generation event with token counts."""
        if not self._enabled or self._lf is None:
            return
        try:
            parent.generation(
                name=name,
                model=model,
                usage={
                    "prompt_tokens": prompt_tokens,
                    "completion_tokens": completion_tokens,
                    "total_tokens": prompt_tokens + completion_tokens,
                },
                input=input_text,
                output=output_text,
            )
        except Exception as exc:
            log.debug("Langfuse generation log failed", error=str(exc))

    def flush(self) -> None:
        if self._enabled and self._lf:
            try:
                self._lf.flush()
            except Exception:
                pass


# Module-level singleton — initialised lazily on first import.
_tracer: Tracer | None = None


def get_tracer() -> Tracer:
    global _tracer
    if _tracer is None:
        from app.config import get_settings

        s = get_settings()
        _tracer = Tracer(
            enabled=s.langfuse_enabled,
            public_key=s.langfuse_public_key,
            secret_key=s.langfuse_secret_key,
            host=s.langfuse_host,
        )
    return _tracer
