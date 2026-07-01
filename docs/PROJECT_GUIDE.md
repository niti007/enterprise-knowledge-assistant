# Project Guide — Enterprise Knowledge Assistant
### A plain-English, teach-it-to-anyone walkthrough

This document explains the **whole project**: what it is, why each piece exists, and
how the code works — in simple words, with the key code shown and explained. Read it
top to bottom to teach or demo the project.

Links:
- **Live demo:** https://Nitishgalat-enterprise-knowledge-assistant.hf.space
- **Code:** https://github.com/niti007/enterprise-knowledge-assistant

---

## 1. What is this project? (the one-minute version)

Big companies have thousands of documents — policies, manuals, step-by-step guides
(SOPs), incident reports, FAQs, plus data in spreadsheets. Employees waste time hunting
for answers, and normal search is bad at questions that need *connecting the dots*
(e.g. "if the Payment system breaks, what else breaks and who do I call?").

We built a **smart assistant** that:
- Reads all those documents and answers questions in plain language.
- **Shows its sources** (so you can trust the answer).
- Can **reason across connected facts** (multi-step questions).
- **Refuses unsafe requests** and **hides private data**.
- **Records everything** so we can see how well it's doing.

Think of it as a **very well-read librarian** who has also memorized an **org chart /
family tree** of how all the company's systems and teams connect — and who always cites
the exact document a fact came from.

---

## 2. The big picture (how a question flows)

When you ask a question, it travels through a pipeline (an assembly line). Each station
does one job:

```
Your question
   ↓
1. Input guard      → is this safe? hide any private info (emails, SSNs)
   ↓
2. Memory (cache)   → have we answered something almost identical? if yes, reuse it (instant)
   ↓
3. Router           → is this easy or hard? pick a cheap or a smarter AI model
   ↓
4. Agent + tools    → search documents + the relationship graph, re-rank the best bits
   ↓
5. AI writes answer → using ONLY what it found, with [Source: ...] tags
   ↓
6. Output guard     → double-check: is it grounded? any private data or toxic text?
   ↓
7. Logging          → record time taken, tokens used, each step (Langfuse)
   ↓
Answer + sources back to you
```

The single file that runs this assembly line is [`app/pipeline.py`](../app/pipeline.py).

---

## 3. The four big ideas (pillars)

The project combines four things that normally live in separate tutorials:

1. **Hybrid RAG** — "RAG" = *Retrieval-Augmented Generation* = find relevant text first,
   then let the AI answer using that text (so it doesn't make things up). **Hybrid**
   because we search two different stores: a **vector database** (for meaning) and a
   **graph database** (for relationships).
2. **Agent with tools** — instead of one fixed step, the AI can *decide* to use tools:
   search documents, search the web, run a database query, or do a calculation.
3. **Guardrails** — safety checks on the way in (block attacks, hide private data) and on
   the way out (make sure the answer is grounded, not toxic).
4. **Production infrastructure** — an API, a chat UI, monitoring, caching, and choosing
   the right model for cost — the boring-but-vital stuff that makes it real.

---

## 4. The technology choices — and *why* (this part matters in interviews)

| We used | Instead of | Why |
|---|---|---|
| **OpenRouter** for the AI | OpenAI directly | One key, 300+ models, OpenAI-compatible. Flexible + cheap. |
| **Local embeddings** (runs on our machine) | Paid embedding API | OpenRouter has **no** embedding service, and local is **free**. |
| **Neo4j Aura** (cloud graph DB) | Neo4j via Docker | No Docker install needed; free cloud tier; works from anywhere. |
| **ChromaDB** | Pinecone/Weaviate | Simple, local, free, saves to a folder. |
| **fakeredis** (in-memory) | a real Redis server | Same code as Redis, but nothing to install — perfect for a demo. |
| **gpt-4o family** | gpt-4.1 family | gpt-4.1 broke the agent's tool-calling on OpenRouter (see §12). |
| **Chainlit** | React/Next.js | Purpose-built chat UI for AI apps; shows tool steps + sources for free. |
| **Hugging Face Spaces** | AWS/GCP | Free, enough memory for the ML libraries, gives a public URL. |

**Embedding**, **AI model**, **graph**, and **monitoring** are all configured in one
place — [`app/config.py`](../app/config.py) — which reads a `.env` file. Nothing secret
is written in the code.

---

## 5. The data — what we made and why

There was no real company data, so we **generated fake-but-realistic data** that all
**cross-references itself** (the same people, teams, and systems appear across many
documents). That consistency is what makes multi-step questions answerable.

File: [`app/ingestion/generate_fake_data.py`](../app/ingestion/generate_fake_data.py)
produces ~25 files in `data/raw/`:
- Incident reports (`INC-204.md`), step-by-step guides (`SOP-17.md`), manuals, an FAQ.
- Spreadsheets: `users.csv`, `products.csv`, `transactions.csv`.

We then load the **same** data into **two different databases**, because each answers a
different *kind* of question:

**A) ChromaDB (vector database) — for "what does it say?"**
It stores the **text**, turned into lists of numbers ("embeddings") that capture
*meaning*. Similar meaning → similar numbers. Great for "what's the refund policy?"

**B) Neo4j (graph database) — for "how are things connected?"**
It stores **things** (people, teams, systems) as dots and **relationships** as arrows
(`DEPENDS_ON`, `OWNS`, `MANAGES`). Great for "what depends on Auth-DB and who owns it?"

**One document → both stores (worked example):**
The incident report `INC-204.md` says *"Payment-Service outage was caused by Auth-DB
hitting connection limits. Billing team, led by Priya Sharma, owns Payment-Service and
restored it per SOP-17."*
- Into **ChromaDB** go the text chunks (for meaning search).
- Into **Neo4j** go the connections:
  `Payment-Service —DEPENDS_ON→ Auth-DB`, `Billing —OWNS→ Payment-Service`,
  `Priya-Sharma —MANAGES→ Billing`, `Payment-Service —RESOLVED_BY→ SOP-17`.

---

## 6. How the code works, component by component

Everything reads its configuration from **one settings object**. Example:

```python
# app/config.py — one place for all settings, loaded from .env
class Settings(BaseSettings):
    openai_api_key: str = Field(...)          # required; app refuses to start without it
    openai_base_url: Optional[str] = None      # set to OpenRouter's URL
    embedding_provider: str = "openai"         # we set this to "local"
    llm_default_model: str = "gpt-4o-mini"     # cheap/fast model
    llm_advanced_model: str = "gpt-4o"         # smarter model for hard questions
```
*Why:* keeping all knobs in one file means we can switch AI provider, model, or database
by editing `.env` — never the code.

### 6.1 Turning documents into searchable numbers (embeddings + ChromaDB)

The **embedding function** turns text into a vector of numbers. We use a **local** model
so it's free and needs no API:

```python
# app/retrieval/embeddings.py
if settings.embedding_provider == "local":
    return embedding_functions.ONNXMiniLM_L6_V2()   # runs on your machine, no key
```

The **chunker** ([`app/ingestion/chunker.py`](../app/ingestion/chunker.py)) breaks long
documents into ~500-word pieces (with a little overlap so we don't cut a sentence's
meaning in half), then hands them to ChromaDB, which embeds and stores them. We give
ChromaDB the **text** and let it embed — so indexing and searching always use the *same*
method (that consistency is critical; mismatched embeddings = broken search).

### 6.2 Searching by meaning (vector search)

```python
# app/retrieval/vector_search.py (simplified)
collection.query(query_texts=[query], n_results=k)   # returns the k closest chunks
```
ChromaDB embeds your question the same way and returns the closest chunks by meaning.

### 6.3 Building the relationship graph (Neo4j)

We ask the AI to **read each document and pull out entities + relationships as JSON**:

```python
# app/ingestion/graph_builder.py — the AI returns strict JSON like:
# {"entities":[{"name":"Payment-Service","type":"Service"}],
#  "relations":[{"source":"Payment-Service","type":"DEPENDS_ON","target":"Auth-DB"}]}
```
Then we write them to Neo4j with **MERGE** (not CREATE), which means "create it if new,
otherwise reuse it" — so running the builder twice doesn't create duplicates:

```python
# app/ingestion/graph_builder.py
MERGE (n:Entity {name: $name})           # find-or-create the dot
MERGE (a)-[r:DEPENDS_ON]->(b)            # find-or-create the arrow
```
We also seed dots directly from the CSV spreadsheets (no AI needed) — cheap and exact.

### 6.4 Searching the graph (graph search)

Given a question, we find which known entity names it mentions, then **walk 1–2 hops**
out from them and turn the paths into plain sentences:

```python
# app/retrieval/graph_search.py
MATCH path = (a:Entity {name: $seed})-[r*1..2]-(b:Entity) RETURN path
# each relationship becomes text, e.g. "Payment-Service depends on Auth-DB."
```
*Why turn it into sentences?* So graph facts and document chunks look the same to the AI
and can be mixed together.

### 6.5 Mixing both + picking the best (hybrid + re-ranking)

We run vector + graph search, remove duplicates, then use a **re-ranker** — a small model
whose only job is to score "how well does this passage answer *this exact* question?" —
and keep the top few:

```python
# app/retrieval/hybrid.py
pairs = [(query, c["text"]) for c in candidates]
ce_scores = ce.predict(pairs)              # cross-encoder scores each candidate
candidates.sort(key=lambda c: c["rerank_score"], reverse=True)
```
*Why re-rank?* First-pass search is fast but rough. The re-ranker is slower but precise,
so we use it only on the shortlist. Best of both.

### 6.6 The agent and its tools

The **agent** is the decision-maker. We give it four tools and let it choose:

```python
# app/agent/tools.py
retrieve      # hybrid search over documents + graph  (used first, almost always)
web_search    # Tavily web search (turns off politely if no key)
sql_query     # read-only SELECT over the CSV spreadsheets (writes are blocked)
python_exec   # sandboxed calculator (no file/network/import access)
```
The agent is built with **LangGraph** as a small loop: *think → maybe call a tool → look
at the result → think again → answer.* The tools are deliberately **safe**: `sql_query`
refuses anything that isn't a `SELECT`; `python_exec` blocks `import`, file, and network
access. That way the AI can be powerful without being dangerous.

### 6.7 Choosing a model to save money (router)

Not every question needs the expensive model. A few simple rules decide:

```python
# app/routing/model_router.py
if _MULTI_HOP_RE.search(query):      # e.g. "...and who...", "depends on"
    score += 2                        # looks complex → use the smarter model
...
model = advanced_model if score >= 2 else default_model
```
*Why:* easy questions go to the cheap fast model; only genuinely complex ones pay for the
smarter one. Real cost control.

### 6.8 Remembering answers (semantic cache)

If you ask something we've basically answered before, we return it instantly. We compare
questions by **meaning** (embeddings + cosine similarity), not exact text:

```python
# app/caching/semantic_cache.py
score = _cosine_similarity(query_vec, entry["embedding"])
if best_score >= self.threshold:      # 0.92 by default
    return cached_answer               # ~0.6s instead of ~8s
```
*Why "semantic":* "Who owns Payment-Service?" and "Payment-Service — who's the owner?"
are different words, same meaning. Text-matching would miss it; meaning-matching catches
it. Backed by **fakeredis** so there's no server to run.

### 6.9 Safety on the way in (input guardrails)

Before doing anything, we check the question:

```python
# app/guardrails/input_guards.py
# 1) block prompt-injection ("ignore previous instructions", "reveal your system prompt")
# 2) detect & MASK private data with Presidio (emails, SSNs, cards → <REDACTED>)
```
*Why:* stop people from hijacking the assistant, and never let private data flow deeper
into the system or into logs.

### 6.10 Safety on the way out (output guardrails)

After the AI writes an answer, we check it:

```python
# app/guardrails/output_guards.py
# 1) LLM "judge": is this answer actually supported by the sources we found?
# 2) re-scan for private data (mask emails/SSNs/cards)
# 3) toxicity filter (block clearly harmful content)
```
If the judge thinks the answer isn't fully grounded, we don't hide it — we add a gentle
*"parts of this may not be fully grounded"* note. *Why not block?* The judge can be wrong;
flagging is more honest than silently deleting a possibly-correct answer.

### 6.11 Watching everything (observability)

Every request is traced with **Langfuse**: how long each step took, how many tokens were
used, which model, cache hit or miss. This is how you debug and improve a real AI system —
you can't fix what you can't see.

```python
# app/pipeline.py
with tracer.trace("pipeline", ...) as root_trace:
    with tracer.span(root_trace, "input_guards", ...):
        ...
```

### 6.12 The front door (FastAPI) and the face (Chainlit)

- **FastAPI** ([`app/main.py`](../app/main.py)) exposes two endpoints: `GET /health`
  (is it alive?) and `POST /chat` (ask a question, get a structured answer with
  citations). It's the clean API other programs could call.
- **Chainlit** ([`app/chainlit_app.py`](../app/chainlit_app.py)) is the chat website.
  It shows each agent step (🔍 retrieve, 🛡️ guardrails, 🗄️ cache) and the sources.
  In the deployed version it runs the pipeline **in-process** (same program), so there's
  no separate server to keep alive.

---

## 7. Putting it together — the pipeline code

The heart of the app. Read this and you understand the whole flow:

```python
# app/pipeline.py (trimmed to the essential order)
with tracer.trace("pipeline", ...) as root_trace:
    input_result = check_input(message)          # 1. guard + mask PII
    if not input_result["allowed"]:
        return blocked_response                    #    (stop early if unsafe)
    safe_message = input_result["text"]

    cached = cache.get(safe_message)               # 2. semantic cache
    if cached is not None:
        return cached                              #    instant answer

    model, route_info = route_model(safe_message)  # 3. pick cheap vs smart model

    agent_result = run_agent(safe_message, model=model)   # 4. agent + tools + hybrid retrieval
    answer     = agent_result["answer"]
    tool_calls = agent_result["tool_calls"]

    output_result = check_output(answer, context_text)    # 5. hallucination/PII/toxicity
    final_answer = output_result["text"]

    cache.set(safe_message, result)                # 6. remember for next time
    return result                                  #    answer + citations + trace_id
```

If the agent ever errors, we **fall back** to plain vector search so the user still gets
an answer instead of a crash — an important production habit.

---

## 8. How we proved it works (testing & evaluation)

Five kinds of tests, all in `eval/`, results saved in `docs/`:

| Test | What it checks | Result |
|---|---|---|
| **Promptfoo** (`promptfooconfig.yaml`) | 31 real Q&A + safety cases against the API | **29/31 passed (93.5%)** |
| **RAGAS** (`ragas_eval.py`) | Answer quality: faithfulness, relevancy, context precision/recall | faith **0.64**, relevancy **0.80**, recall **0.75** |
| **Safety** (`safety_eval.py`) | 16 attack prompts (injections, PII, harmful, made-up) | **15/16 handled safely (93.8%)** |
| **Load test** (`load_test.py`) | Speed under load + cache benefit | p50 **2.8s**, cache **~6× faster** |
| **Langfuse** | Live traces of every request | screenshots for the report |

**In plain words:**
- *Faithfulness 0.64* = most answers stick to the sources (higher is better).
- *Context recall 0.75* = search usually finds the needed info.
- *Context precision 0.44* = but it also pulls in some irrelevant bits (our known weak
  spot — a good, honest thing to mention when presenting).

---

## 9. How we run and deploy it

- **Local:** create a Python environment, install requirements, fill `.env`, run three
  build scripts (make data → build vector index → build graph), then start the API and
  the Chainlit UI. Full steps are in the [README](../README.md).
- **Cloud:** a **Docker** image on **Hugging Face Spaces**. The secrets (keys, DB URL)
  live as Space secrets, never in the code. On boot it rebuilds the vector index from the
  bundled data and reads the graph from Neo4j Aura. There's even a **GitHub Actions**
  workflow (`.github/workflows/promptfoo.yml`) that can run the Promptfoo tests
  automatically.

---

## 10. Common questions you'll get when presenting

**"Why not just use ChatGPT?"** Plain ChatGPT doesn't know your internal documents and
can make things up. Ours only answers from *your* documents and shows sources.

**"What's the graph for — isn't vector search enough?"** Vector search finds text that
*sounds* similar. It's weak at chains like "A depends on B, B is owned by team C." The
graph stores those links directly, so multi-step questions actually work.

**"How is it safe?"** Two layers of guardrails (in and out), a sandboxed code tool, and a
read-only database tool. Attacks are blocked; private data is masked.

**"How do you know it's good?"** We measured it — Promptfoo, RAGAS, a safety scorecard,
and a load test — instead of just claiming it.

---

## 11. Mini-glossary (jargon → plain words)

- **RAG** — find relevant text first, then let the AI answer using it (stops made-up
  answers).
- **Embedding** — a list of numbers representing a text's meaning; similar meaning →
  similar numbers.
- **Vector database (ChromaDB)** — stores those numbers and finds the closest matches.
- **Graph database (Neo4j)** — stores things and the links between them (an org chart /
  family tree).
- **Re-ranker** — a precise scorer that reorders search results by true relevance.
- **Agent** — an AI that can decide to use tools instead of just replying.
- **Guardrails** — safety checks before and after the AI answers.
- **Semantic cache** — reuses past answers for questions with the *same meaning*.
- **Token** — a chunk of text the AI reads/writes; usage is what you pay for.
- **Observability (Langfuse)** — recording what happened inside each request.
- **Hallucination** — when an AI states something not supported by the sources.

---

## 12. The tricky bugs we hit (great teaching stories)

Real engineering is debugging. These are worth telling:

1. **Dependency conflict at install.** Pinning exact versions made pip give up
   ("ResolutionImpossible"). *Fix:* loosen versions and install in small groups. Lesson:
   over-pinning can be as bad as under-pinning.

2. **OpenRouter has no embeddings.** Our first design assumed OpenAI-style embeddings.
   OpenRouter only does chat. *Fix:* switch embeddings to a **local** model — which also
   made them free. Lesson: check what your provider actually supports.

3. **The agent kept failing tool calls.** The `gpt-4.1` model on OpenRouter uses a newer
   message format that broke the tool conversation. *Fix:* use the `gpt-4o` family, which
   uses the standard format. Lesson: not all models behave the same through a proxy.

4. **The real agent bug (subtle!).** LangGraph was **replacing** the conversation history
   each step instead of **adding** to it, so a tool's reply had no matching question.
   *Fix:* one line — use the `add_messages` reducer so messages append:
   ```python
   messages: Annotated[list, add_messages]   # append, don't overwrite
   ```
   Lesson: in state machines, *how state updates* matters as much as the logic.

5. **First request is slow (~1–2 min), then fast.** The heavy AI libraries load on the
   first question ("cold start"), then stay warm (~6–10s). Lesson: cold-start is normal
   for ML apps; warm it up or set expectations.

---

## 13. File map (where to look)

```
app/
  config.py               # all settings (from .env)
  pipeline.py             # the assembly line — READ THIS FIRST
  main.py                 # FastAPI: /health, /chat
  chainlit_app.py         # the chat website
  ingestion/
    generate_fake_data.py # makes the fake company documents
    chunker.py            # splits docs + stores them in ChromaDB
    graph_builder.py      # AI reads docs → builds the Neo4j graph
  retrieval/
    embeddings.py         # local text→numbers
    vector_search.py      # meaning search (ChromaDB)
    graph_search.py       # relationship search (Neo4j)
    hybrid.py             # combine both + re-rank
  agent/
    graph.py              # the LangGraph decision loop
    tools.py              # retrieve / web_search / sql_query / python_exec
  guardrails/
    input_guards.py       # block attacks + mask PII (in)
    output_guards.py      # grounded? PII? toxic? (out)
  routing/model_router.py # cheap vs smart model
  caching/semantic_cache.py # reuse answers by meaning
  observability/tracing.py  # Langfuse logging
eval/                     # promptfoo, ragas, safety, load tests
docs/                     # ARCHITECTURE, this guide, all reports
```

---

*You now know the whole system — the problem, the design, every component, the tests,
the deployment, and the bugs we beat. Enough to build it, present it, or teach it.*
