# Chapter 12 — The Pipeline: Where Everything Meets (`app/pipeline.py`)

## Why this / what's the need

Every chapter so far taught you one piece of the machine: the guardrails that check messages,
the semantic cache that remembers past answers, the model router that picks which AI model to
use, and the agent that can search documents or call tools. But none of those pieces talk to each
other by themselves. Something has to call them **in the right order** and pass the output of one
into the input of the next.

That "something" is `app/pipeline.py`. Think of it like a **factory assembly line**. A car doesn't
build itself — it moves down a line where station 1 welds the frame, station 2 paints it, station
3 installs the engine, and station 4 does a final inspection before the car rolls out the door. If
station 3 breaks down, a good factory has a backup process so the line doesn't grind to a halt. The
`Pipeline` class is exactly this: it moves a user's message down a line of stations, and if one
station (the agent) breaks, it has a backup station ready to go.

This is the "aha" chapter: once you understand `Pipeline.run`, you understand how the *whole app*
fits together.

> 🔑 **New word — pipeline:** a fixed sequence of processing steps where the output of one step
> becomes the input of the next, like items moving down a factory conveyor belt.

## The five stations, in order

Here is the whole journey a message takes through `Pipeline.run`, station by station:

1. **Input guardrails** — is this message safe/allowed to process?
2. **Semantic cache** — have we already answered something almost identical to this?
3. **Model router** — which AI model should handle this particular question?
4. **Agent** — go retrieve information (documents, graph facts, tools) and draft an answer.
5. **Output guardrails** — is the drafted answer safe/accurate to send back?

Then the result is logged to Langfuse (our tracing tool) and returned.

Let's walk through the real code for each station.

### Setting up the trip: a trace ID and a stopwatch

```python
trace_id = str(uuid.uuid4())
t0 = time.perf_counter()

with tracer.trace("pipeline", session_id=session_id, metadata={"query": message}) as root_trace:
```

- `trace_id = str(uuid.uuid4())` — generates a random unique ID for this one request, so we can
  find it later in our logs or in Langfuse.
- `t0 = time.perf_counter()` — starts a stopwatch so we can measure how long the whole pipeline
  takes (`latency_ms` later).
- `with tracer.trace(...) as root_trace:` — opens a **trace** in Langfuse: a container that will
  record every step below as a nested "span," so you can visually replay the entire request later.

> 🔑 **New word — trace:** a recorded timeline of everything that happened while answering one
> request, used for debugging and understanding AI behavior after the fact.

### Station 1 — Input guardrails (`check_input`)

```python
with tracer.span(root_trace, "input_guards", input={"query": message}):
    from app.guardrails.input_guards import check_input

    input_result = check_input(message)
    guardrail_flags.extend(input_result["flags"])
    guardrail_reasons.extend(input_result["reasons"])

    if not input_result["allowed"]:
        ...
        return { ... "blocked": True, "blocked_reason": input_result["block_reason"] }

    safe_message = input_result["text"]  # PII-masked if applicable
```

- `with tracer.span(root_trace, "input_guards", ...)` — records this step as a labeled block
  inside the trace, so in Langfuse you can see exactly how long input-checking took.
- `input_result = check_input(message)` — calls the guardrail function from an earlier chapter; it
  checks for things like prompt injection or policy violations.
- `guardrail_flags.extend(...)` / `guardrail_reasons.extend(...)` — collect any warning flags and
  human-readable reasons so we can report them later, even if the message isn't fully blocked.
- `if not input_result["allowed"]:` — if the guardrail says "no," the pipeline **stops here** and
  returns immediately with `"blocked": True`. The message never reaches the AI model at all.
- `safe_message = input_result["text"]` — the message going forward, with any personal information
  (PII) masked out. Everything downstream uses `safe_message`, never the raw original.

This is the factory's first inspection station: bad material gets rejected before it wastes time
on the rest of the line.

### Station 2 — Semantic cache

```python
cache = get_semantic_cache()
cached = cache.get(safe_message)

if cached is not None:
    ...
    result["cache_hit"] = True
    ...
    return result
```

- `cache = get_semantic_cache()` — grabs the shared cache object (it remembers past
  question/answer pairs by *meaning*, not exact text).
- `cached = cache.get(safe_message)` — asks: "have we answered something basically like this
  before?"
- `if cached is not None:` — if yes, the pipeline **skips stations 3 and 4 entirely** — no model
  routing, no agent run, no waiting on an AI model — and just returns the saved answer, marked
  `cache_hit=True`. This is a huge speed win for repeated or similar questions.

### Station 3 — Model router (`route_model`)

```python
from app.routing.model_router import route_model

model, route_info = route_model(safe_message)
```

- `from app.routing.model_router import route_model` — only imported here, right when needed
  (this pattern is used throughout the file to keep startup fast and avoid loading unused code).
- `model, route_info = route_model(safe_message)` — looks at the question and decides which AI
  model is the best (and often cheapest) fit — e.g., a small fast model for simple lookups, a
  stronger model for complex reasoning.

### Station 4 — The agent (`run_agent`), with a safety net

```python
for attempt in range(2):
    try:
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
```

- `for attempt in range(2):` — tries the agent **up to twice**. The comment in the source explains
  why: some AI providers occasionally have a hiccup mid-conversation (a dropped "tool call ID"),
  so one retry often just works.
- `agent_result = run_agent(safe_message, model=model)` — this is the star of the previous
  chapter: an agent that can decide, on its own, to search documents, query the knowledge graph,
  or call other tools before answering.
- `answer = agent_result["answer"]` / `tool_calls = agent_result["tool_calls"]` — pull out the
  agent's final written answer and the list of every tool it used along the way (used later for
  citations).
- `except Exception as exc:` — if the agent throws an error on both attempts, we don't crash the
  whole request.
- `answer, tool_calls = self._fallback_vector_rag(...)` — **this is the safety net.** Instead of
  failing, the pipeline falls back to a much simpler method: plain vector search plus a direct
  call to the AI model, no fancy agent tools. It's less capable, but it still gives the user an
  answer instead of an error page. Look inside `_fallback_vector_rag`: it searches the vector
  database directly (`searcher.search`), builds a context block of the retrieved text, and asks
  the model to answer from that context — exactly like a Phase-1, no-agent version of this app.

> 🔑 **New word — fallback:** a simpler backup method the code switches to automatically when the
> preferred method fails, so the user still gets a result.

### Building citations from what the agent actually did

```python
citations = _citations_from_tool_calls(tool_calls)
chunks_retrieved = sum(1 for c in tool_calls if c.get("tool") == "retrieve")
if citations:
    chunks_retrieved = len(citations)
```

- `citations = _citations_from_tool_calls(tool_calls)` — scans through everything the agent's
  `retrieve` tool returned and turns each `[source] text` line into a proper citation object
  (source file, snippet, score) that the frontend can display.
- `chunks_retrieved = ...` — counts how many pieces of retrieved text fed into the answer, purely
  for reporting/monitoring purposes.

### Station 5 — Output guardrails (`check_output`)

```python
with tracer.span(root_trace, "output_guards", input={"answer_preview": answer[:200]}):
    from app.guardrails.output_guards import check_output

    output_result = check_output(answer, context_text=context_text)
    guardrail_flags.extend(output_result["flags"])
    guardrail_reasons.extend(output_result["reasons"])

    if not output_result["allowed"]:
        ...
        return { ... "blocked": True, ... }

    final_answer = output_result["text"]
```

- `output_result = check_output(answer, context_text=context_text)` — checks the *drafted* answer
  for problems like hallucination (making things up not supported by the retrieved context),
  leaked PII, or toxic language.
- `if not output_result["allowed"]:` — if the answer fails this check, the pipeline blocks it and
  returns a safe message instead of the risky one — same pattern as the input guardrail, just at
  the other end of the line.
- `final_answer = output_result["text"]` — the answer that is actually safe to send to the user
  (guardrails may lightly edit the text, e.g. masking PII).

### Finishing up: log to Langfuse, cache the result, return

```python
tracer.log_generation(
    root_trace, name="agent_generate", model=model,
    prompt_tokens=0, completion_tokens=0,
    input_text=safe_message[:500], output_text=final_answer[:500],
)
...
get_semantic_cache().set(safe_message, cache_payload)
```

- `tracer.log_generation(...)` — records the final input/output pair in Langfuse as a
  "generation" event, so you can look it up later by `trace_id`.
- `get_semantic_cache().set(safe_message, cache_payload)` — saves this fresh answer into the
  cache, wrapped in a `try/except` so that if caching fails for any reason, it never breaks the
  response to the user ("best-effort").

## The full order, one more time

`check_input` → `get_semantic_cache().get` → `route_model` → `run_agent` (with `_fallback_vector_rag`
as backup) → `check_output` → log to Langfuse → return dict.

That dict is the exact same shape every time — whether it came from the cache, the agent, or the
fallback — which is why every other part of the app (the API, the frontend) can treat `Pipeline.run`
as one predictable black box.

## ✅ You just learned

- The `Pipeline` class assembles every previous concept (guardrails, cache, router, agent) into
  one ordered sequence via `Pipeline.run`.
- Input guardrails and output guardrails can each independently stop the pipeline early and return
  a `"blocked": True` result.
- A cache hit skips model routing and the agent entirely — a major performance shortcut.
- If the agent errors out (even after one retry), `_fallback_vector_rag` keeps the app answering
  using plain vector search instead of hard-failing.
- Every request gets a `trace_id` and is recorded in Langfuse for later inspection.

## ▶️ Run this now

From the project root, open a Python shell using the project's virtual environment and call the
pipeline directly — no API or web server needed:

```powershell
.venv\Scripts\python.exe -c "from app.pipeline import get_pipeline; import json; r = get_pipeline().run('Who owns the Payment-Service?'); print(json.dumps(r, indent=2)[:800])"
```

You should see a dict printed with `answer`, `citations`, `trace_id`, `model_used`, and more —
exactly the fields described above.

## 🧠 Check yourself

1. If the semantic cache finds a match in Step 2, which later stations (router, agent) still run?
2. Name the two places in `Pipeline.run` where the pipeline can return early with `"blocked": True`.
3. What does `_fallback_vector_rag` do differently from `run_agent`, and when does the pipeline
   use it instead?

Next: [13-api-fastapi.md](13-api-fastapi.md) — how we expose this pipeline over the web with FastAPI.
