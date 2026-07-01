"""
app/pipeline.py
===============
Phase-2 full pipeline:
    input guards -> semantic cache check -> model router -> agent
    (hybrid retrieval + tools) -> output guards -> trace

Keeps the SAME return dict shape as Phase 1 (answer, citations, trace_id,
latency_ms, model, chunks_retrieved, prompt_tokens, completion_tokens) and
adds new fields additively: cache_hit, cache_similarity, model_used,
guardrail_flags, guardrail_reasons, tool_calls, blocked.
"""
from __future__ import annotations

import time
import uuid
from typing import Any

import structlog

log = structlog.get_logger(__name__)

# System prompt kept for reference / fallback vector-only generation path.
_SYSTEM_PROMPT = """\
You are an expert Enterprise Knowledge Assistant for ACME Corp.
Answer the user's question ONLY using the provided context passages.
If the answer is not in the context, say "I don't have enough information to answer that."

Rules:
- Be concise and precise.
- Cite your sources inline using [Source: <filename>] notation.
- If multiple sources support the answer, cite all of them.
- Never make up facts not present in the context.
"""


def _build_context_block(chunks: list[dict[str, Any]]) -> str:
    """Format retrieved chunks into a context block for the LLM prompt."""
    parts: list[str] = []
    for chunk in chunks:
        meta = chunk.get("metadata", {})
        source = meta.get("source", "unknown")
        doc_type = meta.get("doc_type", "")
        parts.append(f"[Source: {source} | Type: {doc_type}]\n{chunk['text']}")
    return "\n\n---\n\n".join(parts)


def _extract_citations(chunks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Build citation objects from retrieved chunks."""
    seen: set[str] = set()
    citations: list[dict[str, Any]] = []
    for rank, chunk in enumerate(chunks):
        meta = chunk.get("metadata", {})
        source = meta.get("source", "unknown")
        if source in seen:
            continue
        seen.add(source)
        citations.append({
            "source": source,
            "doc_type": meta.get("doc_type", ""),
            "dept": meta.get("dept", ""),
            "score": chunk.get("score", 0.0),
            "rank": rank + 1,
            "snippet": chunk["text"][:200] + ("…" if len(chunk["text"]) > 200 else ""),
        })
    return citations


def _citations_from_tool_calls(tool_calls: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Best-effort citation extraction from the agent's retrieve-tool output text,
    which is formatted as '[source] text' lines (see agent/tools.py retrieve_tool)."""
    import re

    seen: set[str] = set()
    citations: list[dict[str, Any]] = []
    rank = 0
    for call in tool_calls:
        if call.get("tool") != "retrieve":
            continue
        output = call.get("output", "") or ""
        for line in output.split("\n\n"):
            match = re.match(r"^\[([^\]]+)\]\s*(.*)", line.strip(), re.DOTALL)
            if not match:
                continue
            source, text = match.group(1), match.group(2)
            if source in seen:
                continue
            seen.add(source)
            rank += 1
            doc_type = "graph_fact" if source == "graph" else ""
            citations.append({
                "source": source,
                "doc_type": doc_type,
                "dept": "",
                "score": 0.0,
                "rank": rank,
                "snippet": text[:200] + ("…" if len(text) > 200 else ""),
            })
    return citations


class Pipeline:
    """Full Phase-2 pipeline: guardrails -> cache -> router -> agent -> guardrails -> trace."""

    def __init__(self) -> None:
        self._searcher = None
        self._openai = None

    # ------------------------------------------------------------------
    # Legacy helpers kept for the simple vector-only fallback path
    # ------------------------------------------------------------------
    def _get_searcher(self):
        if self._searcher is None:
            from app.retrieval.vector_search import VectorSearcher
            self._searcher = VectorSearcher()
        return self._searcher

    def _get_openai(self):
        if self._openai is None:
            from openai import OpenAI
            from app.config import get_settings
            s = get_settings()
            self._openai = OpenAI(api_key=s.openai_api_key, base_url=s.openai_base_url)
        return self._openai

    # ------------------------------------------------------------------
    def run(
        self,
        message: str,
        session_id: str | None = None,
        top_k: int | None = None,
    ) -> dict[str, Any]:
        """
        Execute the full pipeline.

        Returns (Phase 1 keys preserved, Phase 2 keys additive)
        -------
        {
            "answer": str,
            "citations": [{source, doc_type, dept, score, snippet}],
            "trace_id": str,
            "latency_ms": float,
            "model": str,
            "chunks_retrieved": int,
            "prompt_tokens": int,
            "completion_tokens": int,
            # Phase 2 additions:
            "cache_hit": bool,
            "cache_similarity": float | None,
            "model_used": str,
            "guardrail_flags": [str, ...],
            "guardrail_reasons": [str, ...],
            "tool_calls": [{"tool": str, "input": Any, "output": str}],
            "blocked": bool,
            "blocked_reason": str | None,
        }
        """
        from app.config import get_settings
        from app.observability.tracing import get_tracer

        settings = get_settings()
        tracer = get_tracer()
        trace_id = str(uuid.uuid4())
        t0 = time.perf_counter()

        guardrail_flags: list[str] = []
        guardrail_reasons: list[str] = []

        with tracer.trace("pipeline", session_id=session_id, metadata={"query": message}) as root_trace:

            # ----------------------------------------------------------------
            # Step 1: Input guardrails (validation, injection, PII mask)
            # ----------------------------------------------------------------
            with tracer.span(root_trace, "input_guards", input={"query": message}):
                from app.guardrails.input_guards import check_input

                input_result = check_input(message)
                guardrail_flags.extend(input_result["flags"])
                guardrail_reasons.extend(input_result["reasons"])

                if not input_result["allowed"]:
                    latency_ms = (time.perf_counter() - t0) * 1000
                    log.warning("input_blocked", reasons=input_result["reasons"])
                    return {
                        "answer": input_result["block_reason"] or "Your message was blocked by input guardrails.",
                        "citations": [],
                        "trace_id": trace_id,
                        "latency_ms": round(latency_ms, 1),
                        "model": settings.llm_default_model,
                        "chunks_retrieved": 0,
                        "prompt_tokens": 0,
                        "completion_tokens": 0,
                        "cache_hit": False,
                        "cache_similarity": None,
                        "model_used": settings.llm_default_model,
                        "guardrail_flags": guardrail_flags,
                        "guardrail_reasons": guardrail_reasons,
                        "tool_calls": [],
                        "blocked": True,
                        "blocked_reason": input_result["block_reason"],
                    }

                safe_message = input_result["text"]  # PII-masked if applicable

            # ----------------------------------------------------------------
            # Step 2: Semantic cache check
            # ----------------------------------------------------------------
            with tracer.span(root_trace, "semantic_cache", input={"query": safe_message}):
                from app.caching.semantic_cache import get_semantic_cache

                cache = get_semantic_cache()
                cached = cache.get(safe_message)

            if cached is not None:
                latency_ms = (time.perf_counter() - t0) * 1000
                result = dict(cached)
                result["trace_id"] = trace_id
                result["latency_ms"] = round(latency_ms, 1)
                result["cache_hit"] = True
                result["guardrail_flags"] = list(set(guardrail_flags + result.get("guardrail_flags", [])))
                result["guardrail_reasons"] = guardrail_reasons + result.get("guardrail_reasons", [])
                result["blocked"] = False
                result["blocked_reason"] = None
                log.info("pipeline_cache_hit", similarity=result.get("cache_similarity"))
                return result

            # ----------------------------------------------------------------
            # Step 3: Model routing
            # ----------------------------------------------------------------
            with tracer.span(root_trace, "model_router", input={"query": safe_message}):
                from app.routing.model_router import route_model

                model, route_info = route_model(safe_message)

            # ----------------------------------------------------------------
            # Step 4: Agent (hybrid retrieval + tools)
            # ----------------------------------------------------------------
            tool_calls: list[dict[str, Any]] = []
            with tracer.span(root_trace, "agent", input={"model": model}):
                from app.agent.graph import run_agent

                agent_error: Exception | None = None
                for attempt in range(2):  # one retry — some OpenRouter providers
                    try:                  # occasionally drop tool_call_id continuity
                        agent_result = run_agent(safe_message, model=model)
                        answer = agent_result["answer"]
                        tool_calls = agent_result["tool_calls"]
                        agent_error = None
                        break
                    except Exception as exc:
                        agent_error = exc
                        log.warning("agent_attempt_failed", attempt=attempt, error=str(exc))

                if agent_error is not None:
                    log.error("agent_failed_falling_back_to_vector_rag", error=str(agent_error))
                    answer, tool_calls = self._fallback_vector_rag(safe_message, model, top_k, settings)

            # Build citations from the retrieve tool call (preferred), else empty.
            citations = _citations_from_tool_calls(tool_calls)
            chunks_retrieved = sum(
                1 for c in tool_calls if c.get("tool") == "retrieve"
            )
            # More precise: count distinct sources cited as a proxy for chunks retrieved
            if citations:
                chunks_retrieved = len(citations)

            context_text = "\n\n".join(
                call.get("output", "") for call in tool_calls if call.get("tool") == "retrieve"
            )

            # ----------------------------------------------------------------
            # Step 5: Output guardrails (hallucination, PII, toxicity)
            # ----------------------------------------------------------------
            with tracer.span(root_trace, "output_guards", input={"answer_preview": answer[:200]}):
                from app.guardrails.output_guards import check_output

                output_result = check_output(answer, context_text=context_text)
                guardrail_flags.extend(output_result["flags"])
                guardrail_reasons.extend(output_result["reasons"])

                if not output_result["allowed"]:
                    latency_ms = (time.perf_counter() - t0) * 1000
                    log.warning("output_blocked", reasons=output_result["reasons"])
                    return {
                        "answer": output_result["text"],
                        "citations": citations,
                        "trace_id": trace_id,
                        "latency_ms": round(latency_ms, 1),
                        "model": model,
                        "chunks_retrieved": chunks_retrieved,
                        "prompt_tokens": 0,
                        "completion_tokens": 0,
                        "cache_hit": False,
                        "cache_similarity": None,
                        "model_used": model,
                        "guardrail_flags": guardrail_flags,
                        "guardrail_reasons": guardrail_reasons,
                        "tool_calls": tool_calls,
                        "blocked": True,
                        "blocked_reason": output_result["block_reason"],
                    }

                final_answer = output_result["text"]

            tracer.log_generation(
                root_trace,
                name="agent_generate",
                model=model,
                prompt_tokens=0,
                completion_tokens=0,
                input_text=safe_message[:500],
                output_text=final_answer[:500],
            )

        latency_ms = (time.perf_counter() - t0) * 1000

        result = {
            "answer": final_answer,
            "citations": citations,
            "trace_id": trace_id,
            "latency_ms": round(latency_ms, 1),
            "model": model,
            "chunks_retrieved": chunks_retrieved,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "cache_hit": False,
            "cache_similarity": None,
            "model_used": model,
            "guardrail_flags": guardrail_flags,
            "guardrail_reasons": guardrail_reasons,
            "tool_calls": tool_calls,
            "blocked": False,
            "blocked_reason": None,
        }

        # Store in semantic cache (best-effort, never blocks response)
        try:
            from app.caching.semantic_cache import get_semantic_cache

            cache_payload = {k: v for k, v in result.items() if k not in ("cache_hit", "cache_similarity")}
            get_semantic_cache().set(safe_message, cache_payload)
        except Exception as exc:
            log.warning("semantic_cache_store_failed", error=str(exc))

        log.info("pipeline_done", latency_ms=result["latency_ms"], citations=len(citations), model=model)
        return result

    # ------------------------------------------------------------------
    def _fallback_vector_rag(
        self, message: str, model: str, top_k: int | None, settings
    ) -> tuple[str, list[dict[str, Any]]]:
        """Simple vector-only RAG fallback used if the LangGraph agent errors
        out (e.g. tool/runtime issue) — keeps the pipeline answering rather
        than hard-failing."""
        searcher = self._get_searcher()
        k = top_k or settings.retrieval_top_k
        chunks = searcher.search(message, k=k)
        context_block = _build_context_block(chunks)
        user_prompt = f"Context passages:\n\n{context_block}\n\nQuestion: {message}\n\nAnswer:"

        client = self._get_openai()
        completion = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.1,
            max_tokens=1024,
        )
        answer = completion.choices[0].message.content or ""

        # Synthesize a fake "retrieve" tool_call so downstream citation/context
        # extraction works the same way as the agent path.
        retrieve_output = "\n\n".join(
            f"[{c['metadata'].get('source', 'unknown')}] {c['text']}" for c in chunks
        )
        tool_calls = [{"tool": "retrieve", "input": message, "output": retrieve_output}]
        return answer, tool_calls


# Module-level singleton
_pipeline: Pipeline | None = None


def get_pipeline() -> Pipeline:
    global _pipeline
    if _pipeline is None:
        _pipeline = Pipeline()
    return _pipeline
