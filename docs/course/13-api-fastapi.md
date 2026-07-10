# Chapter 13 — Serving the Pipeline Over the Web with FastAPI (`app/main.py`)

## Why this / what's the need

The `Pipeline` you met in the last chapter is just Python code sitting on your computer. That's
fine if you're the only one running it from a script — but what if a website, a mobile app, or a
teammate on another machine wants to ask it a question? They can't just "import" your Python file
over the internet. They need a standard, agreed-upon way to send a question in and get an answer
back, over a network connection.

That's what an **API** gives us. Think of a restaurant: you (the customer/UI) don't walk into the
kitchen and cook your own food. You tell a **waiter** what you want, the waiter carries your order
to the kitchen (the pipeline), and brings the finished dish back to your table. The waiter doesn't
need to know how to cook — they just need a clear, consistent way to take orders and deliver
results. `app/main.py` is our waiter: it's built with **FastAPI**, a Python tool for building APIs.

We use FastAPI specifically because it gives us, almost for free:
- **Automatic validation** — if someone sends a malformed order (e.g. an empty message), FastAPI
  rejects it before our code even runs, with a clear error.
- **Automatic documentation** — FastAPI reads our code and generates an interactive webpage
  (`/docs`) showing every endpoint, so anyone can see exactly what orders are available and try
  them.
- **A clean contract** — the shapes of requests and responses are explicitly defined, so any
  client (web app, mobile app, another script) knows exactly what to send and what it'll get back.

> 🔑 **New word — API (Application Programming Interface):** a defined set of "doors" a program
> exposes so other programs can ask it to do things, without needing to know how it works inside.

> 🔑 **New word — endpoint:** one specific door in an API — a URL plus an action (like "get" or
> "post") that does one particular job, e.g. `/health` or `/chat`.

> 🔑 **New word — request:** the message a client sends to an API asking it to do something (here,
> "please answer this question").

> 🔑 **New word — response:** the message the API sends back with the result.

> 🔑 **New word — JSON:** a simple text format for structuring data (like `{"message": "hi"}`)
> that almost every programming language can read and write — it's how requests and responses are
> packaged.

## Setting up the app and letting any client connect

```python
app = FastAPI(
    title="Enterprise Knowledge Assistant",
    description="Hybrid RAG (vector + graph) knowledge assistant with citations and tracing.",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

- `app = FastAPI(title=..., description=..., version=...)` — creates the FastAPI application
  itself; the `title`/`description` also show up automatically on the auto-generated docs page.
- `app.add_middleware(CORSMiddleware, allow_origins=["*"], ...)` — tells browsers "any website is
  allowed to call this API." Without this, web browsers block cross-site requests by default for
  security. The comment `# restrict in production` is a reminder that `"*"` (allow everyone) is
  convenient for development but should be locked down to specific trusted sites in a real
  deployment.

## Startup check

```python
@app.on_event("startup")
async def startup_event() -> None:
    from app.config import get_settings
    settings = get_settings()
    log.info("startup", env=settings.app_env, model=settings.llm_default_model, ...)
```

- `@app.on_event("startup")` — marks this function to run once, automatically, the moment the
  server boots up (not on every request).
- `settings = get_settings()` — loads and validates configuration (API keys, model names, file
  paths) immediately. If something required is missing, the app fails loudly right at startup
  instead of failing confusingly on the first real question.

## The request and response shapes (`ChatRequest`, `ChatResponse`)

```python
class ChatRequest(BaseModel):
    session_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    message: str = Field(..., min_length=1, max_length=4096, description="User query")
    top_k: int = Field(default=5, ge=1, le=20, description="Number of chunks to retrieve")
```

- `class ChatRequest(BaseModel):` — defines exactly what a valid `/chat` request must look like,
  using **Pydantic** (FastAPI's validation library).
- `session_id: str = Field(default_factory=...)` — if the client doesn't send one, a random ID is
  generated automatically so conversations can still be tracked.
- `message: str = Field(..., min_length=1, max_length=4096, ...)` — the `...` means "required."
  FastAPI will automatically reject any request with a missing, empty, or overly long message —
  no code of ours has to check that by hand.
- `top_k: int = Field(default=5, ge=1, le=20, ...)` — how many document chunks to retrieve; must
  be between 1 and 20, defaulting to 5. Again, FastAPI enforces this automatically.

```python
class ChatResponse(BaseModel):
    session_id: str
    answer: str
    citations: list[CitationModel]
    trace_id: str
    latency_ms: float
    model: str
    chunks_retrieved: int
    cache_hit: bool = False
    ...
```

- `class ChatResponse(BaseModel):` — defines exactly what shape every `/chat` reply will have.
  Because it's explicit, any client integrating with this API knows precisely what fields to
  expect — `answer`, `citations`, `trace_id`, and so on — matching the same dict shape produced by
  `Pipeline.run` from the last chapter.
- Fields with a default (like `cache_hit: bool = False`) are additive Phase-2 fields: older
  clients that don't know about them simply ignore them; nothing breaks.

## `GET /health` — is the service alive?

```python
@app.get("/health", response_model=HealthResponse, tags=["infra"])
async def health() -> HealthResponse:
    chroma_count: int | None = None
    try:
        from app.ingestion.chunker import get_chroma_collection
        collection = get_chroma_collection()
        chroma_count = collection.count()
    except Exception:
        pass
    return HealthResponse(status="ok", version="1.0.0", uptime_s=..., chroma_count=chroma_count)
```

- `@app.get("/health", response_model=HealthResponse, tags=["infra"])` — registers a **GET**
  endpoint at `/health`. GET means "just give me information, don't change anything." `tags`
  groups it neatly in the auto-generated docs page.
- `collection.count()` — as a bonus check, it also asks the vector database (Chroma) how many
  document chunks it currently holds, wrapped in `try/except` so a Chroma problem never breaks the
  health check itself.
- This endpoint is what load balancers, monitoring tools, or `docker` health checks use to confirm
  "yes, this service is up and ready."

## `POST /chat` — the main event

```python
@app.post("/chat", response_model=ChatResponse, tags=["chat"])
async def chat(request: ChatRequest) -> ChatResponse:
    if not request.message.strip():
        raise HTTPException(status_code=400, detail="message cannot be empty")

    if request.session_id not in _sessions:
        _sessions[request.session_id] = []
    _sessions[request.session_id].append({"role": "user", "content": request.message})

    try:
        from app.pipeline import get_pipeline
        pipeline = get_pipeline()
        result = pipeline.run(message=request.message, session_id=request.session_id, top_k=request.top_k)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Pipeline error: {exc}")
```

- `@app.post("/chat", ...)` — registers a **POST** endpoint. POST means "here's data, please do
  something with it" (as opposed to GET's "just fetch"). Since asking a question involves sending
  data (the message) and doing real work (running the pipeline), POST is the right choice.
- `async def chat(request: ChatRequest)` — because the parameter is typed as `ChatRequest`,
  FastAPI automatically parses the incoming JSON, validates it against the rules we saw above, and
  hands you a ready-to-use Python object. If validation fails, FastAPI sends back a clear error
  automatically — your function body never even runs.
- `_sessions[request.session_id].append(...)` — keeps a simple in-memory log of the conversation
  per session (the code comments note this would move to Redis in a bigger production setup).
- `pipeline = get_pipeline()` then `pipeline.run(...)` — this is the entire point of the endpoint:
  hand the validated message straight to the `Pipeline` from Chapter 12. The API layer doesn't
  know or care *how* the answer is produced — guardrails, cache, router, agent, fallback — it just
  calls `get_pipeline().run()` and waits for the result dict.
- `except RuntimeError` / `except Exception` — turns internal Python errors into proper HTTP error
  responses (503 for expected setup problems like an empty index, 500 for anything unexpected)
  instead of letting the server crash or return a confusing raw traceback.

```python
    return ChatResponse(
        session_id=request.session_id,
        answer=result["answer"],
        citations=[CitationModel(**c) for c in result["citations"]],
        trace_id=result["trace_id"],
        ...
    )
```

- `return ChatResponse(...)` — repackages the pipeline's raw dict into the strict `ChatResponse`
  shape. FastAPI then automatically converts this Python object into JSON to send back over the
  network.

## The 404-style safety net

```python
@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    log.error("unhandled_error", path=request.url.path, error=str(exc))
    return JSONResponse(status_code=500, content={"detail": str(exc)})
```

- `@app.exception_handler(Exception)` — a catch-all: if literally anything unexpected goes wrong
  anywhere in the app, this makes sure the client still gets back a valid JSON error response
  (with status 500) instead of the connection just dying.

## ✅ You just learned

- An API is a defined set of doors (endpoints) other programs can use to ask your code to do
  things, without needing to see inside — like a restaurant waiter carrying orders to the kitchen.
- FastAPI gives us automatic request validation (`ChatRequest`), automatic response shaping
  (`ChatResponse`), and free interactive documentation.
- `GET /health` is a no-side-effects check that the service (and Chroma) is alive.
- `POST /chat` validates the incoming question, calls `get_pipeline().run()` to do the real work,
  and reshapes the result into a `ChatResponse`.
- The API layer is intentionally thin — all the real intelligence lives in `Pipeline`, exactly as
  we saw in Chapter 12.

## ▶️ Run this now

Start the API server (from the project root, using the project's virtual environment):

```powershell
.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8001
```

In a second terminal, check that it's alive:

```powershell
curl http://127.0.0.1:8001/health
```

You should get back JSON like `{"status":"ok","version":"1.0.0","uptime_s":...,"chroma_count":...}`.
You can also open `http://127.0.0.1:8001/docs` in a browser to see FastAPI's auto-generated,
interactive documentation page and try `/chat` right from there.

## 🧠 Check yourself

1. Why does `POST /chat` use POST instead of GET?
2. What happens if a client sends a `/chat` request with an empty `message` field — where is that
   rejected, and does any of our own code have to check for it?
3. Which single line inside the `chat()` function actually produces the answer, and what chapter
   explained what happens inside it?

Next: [14-frontend-chainlit.md](14-frontend-chainlit.md) — how we build the chat website that
talks to (or replaces) this API.
