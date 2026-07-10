# Chapter 11 — Observability: The Dashcam for Your AI App

## Why this / what's the need

Think of a delivery truck fitted with a dashcam and a flight recorder ("black box"). While the truck drives around, nobody's watching it live every second — but if something goes wrong (a late delivery, a crash, a complaint), you can pull the recording and see exactly what happened: where it stopped, how long each leg of the trip took, what route it drove.

An AI pipeline is the same. A single user question might trigger: a guardrail check, a cache lookup, a document retrieval step, a model call, another guardrail check on the output. If the answer is slow, wrong, or expensive, you need to see *inside* that chain of steps after the fact — not guess.

> 🔑 **New word — observability:** The ability to look inside a running system after (or while) it does its work, to understand what happened, how long it took, and where it might have gone wrong — instead of the system being a total "black box" you can only guess about.

This project uses **Langfuse**, a tool built specifically for tracing AI/LLM applications, wrapped by `app/observability/tracing.py`.

---

## What does Langfuse actually record?

For each user request, the tracing code can capture:
- **Latency** — how long each step (retrieval, generation, guardrail check) took.
- **Tokens** — how much text went in and came out of each AI model call.

> 🔑 **New word — token:** A small chunk of text (roughly a word or part of a word) that an AI model reads or writes. AI providers charge money per token, so counting tokens tells you what an answer actually cost.

- **Steps** — the individual stages of the pipeline (a "trace" containing nested "spans"), so you can see the whole journey of one request, not just the final answer.

Without this, if a user says "the app was slow" or "the app said something wrong," you'd have no way to see *why* — which step was slow, which model was used, whether the cache was hit, how many tokens were burned. Observability turns "the app failed" into "the retrieval step took 4 seconds and the hallucination judge flagged the answer" — something you can actually act on.

---

## Degrading gracefully when Langfuse isn't configured

A core design choice in this file: if Langfuse isn't set up (no API keys), the app must **still work perfectly** — it just won't record anything. This is done with a "no-op" stand-in object.

```python
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
```
- `_NoopSpan` — a fake stand-in for a real Langfuse "span" object. "No-op" means "no operation" — calling its methods does nothing.
- `self.id = str(uuid.uuid4())` — still generates a unique ID, so any code that expects a trace ID doesn't break even when tracing is off.
- `def update(self, **_): pass` / `def end(self, **_): pass` — these methods accept any arguments and simply do nothing, so the rest of the codebase can call `span.update(...)` or `span.end(...)` everywhere without needing an `if tracing_enabled` check scattered throughout the app.

### The `Tracer` class

```python
class Tracer:
    def __init__(self, enabled: bool, public_key: str, secret_key: str, host: str):
        self._enabled = enabled
        self._lf = None
        if enabled:
            try:
                from langfuse import Langfuse
                self._lf = Langfuse(public_key=public_key, secret_key=secret_key, host=host)
                log.info("Langfuse tracing enabled", host=host)
            except Exception as exc:
                log.warning("Langfuse init failed — tracing disabled", error=str(exc))
                self._enabled = False
```
- `enabled: bool` — comes from configuration (basically: "do we have real Langfuse API keys?").
- `if enabled: try: ... self._lf = Langfuse(...)` — only tries to connect to Langfuse if it's supposed to be on.
- `except Exception as exc: ... self._enabled = False` — if connecting fails for any reason (bad keys, no internet), tracing quietly turns itself off instead of crashing the whole application. The app keeps working; you just lose the "dashcam footage" for that run.

### Wrapping a whole request: `trace()`

```python
@contextmanager
def trace(self, name, session_id=None, user_id=None, metadata=None):
    if not self._enabled or self._lf is None:
        span = _NoopSpan(name)
        yield span
        return

    trace_obj = self._lf.trace(
        name=name, session_id=session_id, user_id=user_id or "anonymous", metadata=metadata or {},
    )
    try:
        yield trace_obj
    finally:
        try:
            self._lf.flush()
        except Exception:
            pass
```
- `@contextmanager` — makes this usable in a `with tracer.trace(...) as root:` block, so the "start recording / stop recording" bookkeeping happens automatically around whatever code runs inside the `with`.
- `if not self._enabled or self._lf is None: yield _NoopSpan(name); return` — if tracing is off, hand back the harmless fake object instead, and skip everything else.
- `trace_obj = self._lf.trace(...)` — starts one real Langfuse trace representing an entire pipeline run (e.g. one user question, start to finish).
- `finally: ... self._lf.flush()` — makes sure buffered trace data actually gets sent to Langfuse's servers before moving on, even if something inside the `with` block raised an error.

### Wrapping one step: `span()`

```python
@contextmanager
def span(self, parent, name, input=None, metadata=None):
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
```
- `span()` — represents one *sub-step* inside a larger trace (e.g. "retrieval" or "guardrail_check"), nested under the parent trace.
- `start = time.perf_counter()` ... `latency_ms = (time.perf_counter() - start) * 1000` — measures exactly how long the code inside the `with` block took, in milliseconds, and records it — this is where per-step latency actually gets captured.
- `span_obj.end(metadata={"latency_ms": latency_ms})` — attaches that timing to the span record in Langfuse.

### Recording an AI model call: `log_generation()`

```python
def log_generation(self, parent, name, model, prompt_tokens, completion_tokens, input_text="", output_text=""):
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
```
- This is specifically for logging an LLM call (as opposed to a generic step): it records which `model` was used, and the token counts (`prompt_tokens` in, `completion_tokens` out).
- `"total_tokens": prompt_tokens + completion_tokens` — combines both, since AI providers typically bill per total token.
- Storing `input_text`/`output_text` alongside the numbers lets you go back later and actually *read* what was asked and answered for any given call — crucial for debugging a wrong or weird response.

### One shared tracer for the whole app

```python
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
```
- Just like the semantic cache in the previous chapter, this uses a **singleton** — one shared `Tracer` object built once (from config) and reused everywhere, instead of reconnecting to Langfuse repeatedly.

---

## Why you need this for a *real* AI system

Without observability, an AI system is a black box: you ask it a question, you get an answer, and if something's wrong, you're stuck guessing. With tracing wired through every guardrail check, cache lookup, retrieval step, and model call, you can answer questions like:
- "Why did this specific answer take 6 seconds?" (look at the span latencies)
- "Why did this answer cost more than expected?" (look at the token counts and which model was routed to)
- "Did the cache actually get used here, or did we hit the model again?" (look at the trace's steps)
- "What exactly did the model see and say?" (the recorded `input_text`/`output_text`)

This is exactly why the earlier chapters' `route_model` and `SemanticCache` both call `log.info(...)` on every decision — those logs, combined with Langfuse traces, are what make the difference between "the app is a mystery" and "the app is debuggable."

---

## ✅ You just learned
- Observability means being able to see inside your running system after the fact — latency, tokens, and steps — instead of treating it as a black box.
- Langfuse is the tracing tool used here; `Tracer` wraps it with `trace()` (whole request), `span()` (one step), and `log_generation()` (one AI model call, with token counts).
- When Langfuse isn't configured, `_NoopSpan` and the `enabled` flag let the app keep running exactly the same, just without recording anything — nothing ever crashes because tracing is off.
- A single shared `Tracer` singleton (via `get_tracer()`) is used app-wide, just like the semantic cache singleton from the last chapter.

## ▶️ Run this now

```
.venv\Scripts\python.exe
```

```python
from app.observability.tracing import get_tracer

tracer = get_tracer()

with tracer.trace("demo_pipeline", session_id="s1", user_id="test-user") as root:
    with tracer.span(root, "retrieval", input={"query": "hello"}) as span:
        # pretend some work happens here
        pass
    tracer.log_generation(
        root, name="answer_generation", model="gpt-4o-mini",
        prompt_tokens=120, completion_tokens=40,
        input_text="hello", output_text="Hi there!",
    )

print("Done — if Langfuse keys aren't set, this ran as a no-op with zero errors.")
```

If you don't have Langfuse API keys configured, this still runs cleanly — you just won't see anything appear on a Langfuse dashboard, because `_NoopSpan` quietly absorbed every call.

## 🧠 Check yourself
1. What specifically happens (return value, behavior) when you call `tracer.span(...)` but Langfuse is disabled?
2. Name three things a Langfuse trace can tell you about a single user request.
3. Why does `log_generation` record both token counts *and* the actual input/output text, rather than just the token counts?

Next we tie every piece together into one assembly line →
[12-pipeline.md](12-pipeline.md)
