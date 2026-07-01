"""
app/chainlit_app.py
====================
Chainlit frontend for the Enterprise Knowledge Assistant.

Calls FastAPI /chat endpoint (or the pipeline directly if FAST_API_URL is unset).

Run:
    chainlit run app/chainlit_app.py --port 8000
(Keep uvicorn running on port 8001 in another terminal.)
"""
from __future__ import annotations

import os
import sys
import uuid
from pathlib import Path

# Make sure repo root is on the path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import chainlit as cl
import httpx

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
FASTAPI_URL = os.getenv("FASTAPI_URL", "http://localhost:8001")
LANGFUSE_HOST = os.getenv("LANGFUSE_HOST", "https://cloud.langfuse.com")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _format_citations(citations: list[dict]) -> str:
    if not citations:
        return ""
    lines = ["**Sources:**"]
    for c in citations:
        score_pct = int(c.get("score", 0) * 100)
        lines.append(
            f"- `{c['source']}` ({c.get('doc_type', 'doc')}, {score_pct}% match)"
        )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Chainlit lifecycle
# ---------------------------------------------------------------------------

@cl.on_chat_start
async def on_chat_start() -> None:
    """Initialise a session when the user opens the chat."""
    session_id = str(uuid.uuid4())
    cl.user_session.set("session_id", session_id)
    await cl.Message(
        content=(
            "👋 Welcome to the **Enterprise Knowledge Assistant**!\n\n"
            "Ask me anything about company policies, SOPs, systems, or incidents.\n\n"
            "_Try:_ \"Who owns the Payment-Service?\" or \"What caused the March 2026 outage?\""
        )
    ).send()


@cl.on_message
async def on_message(message: cl.Message) -> None:
    """Handle incoming user messages."""
    session_id = cl.user_session.get("session_id") or str(uuid.uuid4())
    query = message.content.strip()

    if not query:
        return

    # ----------------------------------------------------------------
    # Run the pipeline IN-PROCESS (guardrails, cache, routing, agent+tools,
    # guardrails). Pipeline.run is blocking, so execute it in a worker thread
    # to keep the Chainlit event loop responsive. We surface each stage as a
    # cl.Step afterwards using the fields returned in the result dict.
    #
    # If USE_REMOTE_API=1 and FASTAPI_URL is set, call the HTTP backend instead.
    # ----------------------------------------------------------------
    async with cl.Step(name="🧠 Knowledge Assistant pipeline", type="tool") as call_step:
        call_step.input = query
        try:
            if os.getenv("USE_REMOTE_API") == "1":
                async with httpx.AsyncClient(timeout=180.0) as client:
                    resp = await client.post(
                        f"{FASTAPI_URL}/chat",
                        json={"session_id": session_id, "message": query, "top_k": 5},
                    )
                    resp.raise_for_status()
                    data = resp.json()
            else:
                import asyncio

                from app.pipeline import get_pipeline

                data = await asyncio.to_thread(get_pipeline().run, query, session_id, 5)
        except Exception as exc:
            await cl.Message(content=f"❌ Pipeline error: {exc}").send()
            return

        call_step.output = "done"

    # ----------------------------------------------------------------
    # Step indicator: Guardrails / cache
    # ----------------------------------------------------------------
    guardrail_flags = data.get("guardrail_flags", [])
    guardrail_reasons = data.get("guardrail_reasons", [])
    cache_hit = data.get("cache_hit", False)

    if guardrail_flags:
        async with cl.Step(name="🛡️ Guardrails", type="tool") as guard_step:
            guard_step.input = "input + output checks"
            guard_step.output = (
                f"Flags: {', '.join(guardrail_flags)}\n" + "\n".join(f"- {r}" for r in guardrail_reasons)
            )

    async with cl.Step(name="🗄️ Semantic cache", type="tool") as cache_step:
        cache_step.input = query
        if cache_hit:
            sim = data.get("cache_similarity")
            cache_step.output = f"HIT (similarity={sim})" if sim is not None else "HIT"
        else:
            cache_step.output = "MISS — generated fresh answer"

    # ----------------------------------------------------------------
    # Step indicator: Agent tool calls (retrieve/web_search/sql_query/python_exec)
    # ----------------------------------------------------------------
    for call in data.get("tool_calls", []):
        tool_name = call.get("tool", "tool")
        icon = {
            "retrieve": "🔍", "web_search": "🌐", "sql_query": "🗃️", "python_exec": "🧮",
        }.get(tool_name, "🔧")
        async with cl.Step(name=f"{icon} {tool_name}", type="tool") as tool_step:
            tool_step.input = str(call.get("input", ""))[:500]
            tool_step.output = str(call.get("output", ""))[:1000]

    # ----------------------------------------------------------------
    # Step indicator: Generation
    # ----------------------------------------------------------------
    async with cl.Step(name="🤖 Generating answer", type="llm") as gen_step:
        gen_step.input = f"Model: {data.get('model_used') or data.get('model', 'unknown')}"
        gen_step.output = f"Latency: {data.get('latency_ms', 0):.0f} ms"

    if data.get("blocked"):
        await cl.Message(content=f"🚫 {data.get('answer', 'Request blocked by guardrails.')}").send()
        return

    # ----------------------------------------------------------------
    # Main answer message
    # ----------------------------------------------------------------
    answer = data.get("answer", "No answer returned.")
    citations = data.get("citations", [])
    latency_ms = data.get("latency_ms", 0)
    trace_id = data.get("trace_id", "")
    model = data.get("model_used") or data.get("model", "")

    # Build footer with meta info
    langfuse_url = f"{LANGFUSE_HOST}/trace/{trace_id}" if trace_id else ""
    footer_parts = [f"⏱ {latency_ms:.0f} ms", f"🤖 {model}"]
    if cache_hit:
        footer_parts.append("🗄️ cache hit")
    if guardrail_flags:
        footer_parts.append(f"🛡️ {','.join(guardrail_flags)}")
    if langfuse_url:
        footer_parts.append(f"[🔭 Trace]({langfuse_url})")
    footer = " | ".join(footer_parts)

    # Citation source elements
    source_elements: list[cl.Text] = []
    for c in citations:
        source_elements.append(
            cl.Text(
                name=c["source"],
                content=f"**{c['source']}** ({c.get('doc_type', '')})\n\n{c.get('snippet', '')}",
                display="side",
            )
        )

    citation_text = _format_citations(citations)
    full_content = answer
    if citation_text:
        full_content += f"\n\n{citation_text}"
    full_content += f"\n\n---\n_{footer}_"

    await cl.Message(
        content=full_content,
        elements=source_elements,
    ).send()
