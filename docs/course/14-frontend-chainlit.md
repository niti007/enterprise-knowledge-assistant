# Chapter 14 — The Chat Website: Chainlit (`app/chainlit_app.py`)

## Why this / what's the need

The FastAPI waiter from Chapter 13 can take orders and deliver dishes — but there's no dining room
yet. No table, no menu, no chairs for customers to actually sit and eat. Someone still has to build
the physical space where a real person types a question and watches an answer (with its sources)
appear on screen.

That's **Chainlit**. It's a ready-made chat website builder specifically for AI apps: with a
handful of Python functions, you get a full chat interface in the browser, complete with message
bubbles, a place to show "the AI is thinking / searching / calling a tool" step-by-step, and a
side panel for citations — all without writing any HTML, CSS, or JavaScript yourself. Chainlit is
the dining room: the place a customer actually sits down, and where the food (and how it was
made) is presented to them.

> 🔑 **New word — frontend:** the part of an application a person actually sees and interacts
> with in their browser, as opposed to the backend code that does the work behind the scenes.

> 🔑 **New word — async / asynchronous:** a way of writing code so it can pause while waiting on
> something slow (like a network call) without freezing the whole program — other work can happen
> during that wait.

> 🔑 **New word — event loop:** the engine that runs an async program; it juggles many waiting
> tasks at once and wakes each one up when its result is ready.

> 🔑 **New word — thread:** a separate track of execution that can run alongside the main one, used
> here so a slow, blocking function doesn't freeze the event loop.

## Two ways to run: in-process, or over the API

```python
"""
Calls FastAPI /chat endpoint (or the pipeline directly if FAST_API_URL is unset).
...
"""
FASTAPI_URL = os.getenv("FASTAPI_URL", "http://localhost:8001")
```

Read that alongside the actual code inside `on_message` further down — that's the behavior that
matters:

```python
if os.getenv("USE_REMOTE_API") == "1":
    async with httpx.AsyncClient(timeout=180.0) as client:
        resp = await client.post(f"{FASTAPI_URL}/chat", json={...})
        data = resp.json()
else:
    import asyncio
    from app.pipeline import get_pipeline
    data = await asyncio.to_thread(get_pipeline().run, query, session_id, 5)
```

By **default** (`USE_REMOTE_API` not set), Chainlit skips the FastAPI waiter entirely and imports
`get_pipeline()` **directly, in-process** — meaning the chat website and the AI pipeline run as
one single Python program, in the same memory space, with no network hop in between. This is how
the app is deployed: one process, no separate FastAPI server required.

Only if you explicitly set `USE_REMOTE_API=1` does Chainlit instead make an HTTP call to
`FASTAPI_URL` (the Chapter 13 API) — useful locally if you want the API and the chat UI running as
two separate processes, e.g. to test the API independently or let other clients share it.

> 🔑 **New word — in-process:** running inside the same running program/memory space as the
> caller, instead of as a separate program reached over a network connection.

Because `Pipeline.run` is a normal, blocking Python function (it does real work and doesn't return
until it's done), calling it directly inside an `async def` function would freeze Chainlit's whole
event loop for everyone while it runs. `asyncio.to_thread(get_pipeline().run, query, session_id, 5)`
solves this: it runs `pipeline.run(query, session_id, 5)` on a separate worker **thread**, and
`await`s the result, so the event loop stays free to handle other users' messages (or UI updates)
while this one request is working.

## `on_chat_start` — greeting a new visitor

```python
@cl.on_chat_start
async def on_chat_start() -> None:
    session_id = str(uuid.uuid4())
    cl.user_session.set("session_id", session_id)
    await cl.Message(content="👋 Welcome to the **Enterprise Knowledge Assistant**! ...").send()
```

- `@cl.on_chat_start` — tells Chainlit "run this function once, the moment a visitor opens a new
  chat session in their browser."
- `session_id = str(uuid.uuid4())` — generates one random ID for this browser session, so all
  their messages can be grouped together (matching the `session_id` concept from Chapter 13).
- `cl.user_session.set("session_id", session_id)` — stores that ID in Chainlit's per-user session
  storage, so later functions (like `on_message`) can retrieve it.
- `await cl.Message(content=...).send()` — builds a chat bubble with a welcome message and
  actually sends it to the user's screen. `await` is needed because sending a message involves a
  network round-trip to the browser (via a WebSocket), which is an async operation.

> 🔑 **New word — WebSocket:** a persistent, two-way connection between browser and server that
> lets the server push new messages to the page instantly, without the browser having to keep
> asking "anything new?".

## `on_message` — handling what the user typed

```python
@cl.on_message
async def on_message(message: cl.Message) -> None:
    session_id = cl.user_session.get("session_id") or str(uuid.uuid4())
    query = message.content.strip()
    if not query:
        return
```

- `@cl.on_message` — tells Chainlit "run this function every time the user sends a new chat
  message."
- `message: cl.Message` — Chainlit hands you the incoming message wrapped in its own `cl.Message`
  object; `.content` is the actual typed text.
- `session_id = cl.user_session.get("session_id") or str(uuid.uuid4())` — retrieves the session ID
  saved in `on_chat_start` (with a safety fallback in case it's somehow missing).
- `if not query: return` — ignores empty submissions.

### Showing the pipeline as a step

```python
async with cl.Step(name="🧠 Knowledge Assistant pipeline", type="tool") as call_step:
    call_step.input = query
    try:
        ...
        data = await asyncio.to_thread(get_pipeline().run, query, session_id, 5)
    except Exception as exc:
        await cl.Message(content=f"❌ Pipeline error: {exc}").send()
        return
    call_step.output = "done"
```

- `async with cl.Step(name=..., type="tool") as call_step:` — creates a **step**: a collapsible,
  labeled block in the UI showing "here's something the assistant did behind the scenes," similar
  to how you might watch a delivery tracker update. `call_step.input`/`.output` set what's shown
  inside it.
- The `try/except` around the pipeline call means if `Pipeline.run` raises an unexpected error
  (rare, since the pipeline itself has its own fallback — Chapter 12), the user still gets a clear
  chat message instead of a frozen or broken page.

### Rendering guardrails and the cache result as steps

```python
if guardrail_flags:
    async with cl.Step(name="🛡️ Guardrails", type="tool") as guard_step:
        guard_step.input = "input + output checks"
        guard_step.output = f"Flags: {', '.join(guardrail_flags)}\n" + ...

async with cl.Step(name="🗄️ Semantic cache", type="tool") as cache_step:
    cache_step.input = query
    if cache_hit:
        cache_step.output = f"HIT (similarity={sim})"
    else:
        cache_step.output = "MISS — generated fresh answer"
```

- Each of these is another `cl.Step`, giving the user visibility into *exactly* which stations from
  the Chapter 12 pipeline fired: did any guardrail flag this message? Was this answer served from
  cache or generated fresh? This turns the pipeline's internal dict fields (`guardrail_flags`,
  `cache_hit`, `cache_similarity`) into a transparent, human-readable trail in the UI.

### Rendering every tool the agent used

```python
for call in data.get("tool_calls", []):
    tool_name = call.get("tool", "tool")
    icon = {"retrieve": "🔍", "web_search": "🌐", "sql_query": "🗃️", "python_exec": "🧮"}.get(tool_name, "🔧")
    async with cl.Step(name=f"{icon} {tool_name}", type="tool") as tool_step:
        tool_step.input = str(call.get("input", ""))[:500]
        tool_step.output = str(call.get("output", ""))[:1000]
```

- Loops over `tool_calls` (the same list built by the agent in Chapter 12/11) and renders **one
  step per tool call**, with a matching icon. This is what lets a user watch, live, that the AI
  actually searched documents (`retrieve`), or queried the web, or ran SQL — instead of just
  trusting a black-box answer.

### The final answer, with citations

```python
if data.get("blocked"):
    await cl.Message(content=f"🚫 {data.get('answer', 'Request blocked by guardrails.')}").send()
    return

...
source_elements: list[cl.Text] = []
for c in citations:
    source_elements.append(cl.Text(name=c["source"], content=f"**{c['source']}** ...", display="side"))

await cl.Message(content=full_content, elements=source_elements).send()
```

- `if data.get("blocked"):` — if the pipeline blocked the request (Chapter 12's guardrail
  short-circuit), show that as the message and stop — no citations or footer needed.
- `source_elements` — builds one `cl.Text` element per citation; passing `display="side"` makes
  Chainlit show it as a clickable side panel item rather than cluttering the main chat bubble.
- `await cl.Message(content=full_content, elements=source_elements).send()` — sends the final
  answer bubble, with the formatted citations appended in the text and the source snippets
  available in the side panel — the last thing the user sees for this turn.

## ✅ You just learned

- Chainlit gives us a full AI chat website (message bubbles, live step tracking, citation panels)
  with just a few Python functions — no HTML/CSS/JS needed.
- By default the app runs the pipeline **in-process** via `asyncio.to_thread(get_pipeline().run, ...)`
  — one single program, no separate API server required in production.
- Setting `USE_REMOTE_API=1` switches Chainlit to instead call the Chapter 13 FastAPI `/chat`
  endpoint over HTTP — handy for local testing with two separate processes.
- `on_chat_start` sets up a fresh session ID and greets the user; `on_message` runs on every
  message the user sends.
- `cl.Step` renders each pipeline stage (guardrails, cache, tool calls) as a visible, inspectable
  block, and `cl.Text` elements render citations in a side panel.

## ▶️ Run this now

From the project root, using the project's virtual environment, start the chat website
(in-process mode, no FastAPI server needed):

```powershell
.venv\Scripts\python.exe -m chainlit run app/chainlit_app.py --port 8000
```

Open `http://127.0.0.1:8000` in your browser, type a question, and watch the `🧠 Knowledge
Assistant pipeline` step, the `🗄️ Semantic cache` step, and any tool-call steps appear before the
final answer with its sources.

## 🧠 Check yourself

1. By default, does `on_message` talk to `app/main.py` over HTTP, or call the pipeline directly?
   What environment variable changes that?
2. Why is `Pipeline.run` wrapped in `asyncio.to_thread(...)` instead of just being called directly
   with `await`?
3. What UI element does Chainlit use to show each individual tool the agent called, and what does
   it display for a `retrieve` call?

Next: [15-run-it.md](15-run-it.md) — putting it all together and running the whole app yourself.
