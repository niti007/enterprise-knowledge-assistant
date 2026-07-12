# V1 — Build + Orchestration Plan (approved)

> This is the first approved plan for the project — the capstone **build** plan, including the
> "Opus is the orchestrator, Sonnet subagents build/validate/repair" execution model.
> Reproduced verbatim from the conversation's first approved-plan block.

---

# Capstone: End-to-End Production GenAI Enterprise Knowledge Assistant

## Context

Building EduHubSpot Module 14 capstone: a production-grade AI Knowledge Assistant. Empty
project dir today (`Full end to end app/`, not yet a git repo). Goal = full-stack app hitting
every rubric item: hybrid RAG (vector + graph), LangGraph agent w/ tools, multi-layer
guardrails, FastAPI serving, Langfuse observability, semantic cache + model routing, plus
deliverable artifacts (Promptfoo 30+ cases, RAGAS report, safety scorecard).

**Decisions locked (user):**
- Frontend = **Chainlit** (purpose-built LLM chat: native citations, step traces, streaming)
- Scope = **Full as-spec** (ChromaDB + Neo4j + Langfuse + all guardrails + evals)
- LLM = **OpenAI** (gpt-4o-mini default, gpt-4o for hard queries via router)

Spec says "full frontend out of scope" → Chainlit stays a thin client over FastAPI `/chat`.

---

## Execution Model — orchestrated subagents (Sonnet 4.6, token-cheap)

I (Opus) = **orchestrator**. I don't write the app code directly; I dispatch Sonnet 4.6
subagents and review their reports. Sonnet = cheaper, this work is mechanical → right model.

**Build → Validate → Repair loop, run PER PHASE** (Phase 1 first, then Phase 2):

1. **Builder agent** (Sonnet 4.6, general-purpose) — given the plan file + phase scope →
   implements that phase's code/files. Returns: what it built + how to run + known gaps.
2. **Validator agent** (Sonnet 4.6, read+run) — runs the phase validation gate / `validate.py` →
   returns a structured PASS/FAIL list (only the failures + exact error msgs, nothing verbose →
   keeps tokens low).
3. **Repair agent** (Sonnet 4.6) — *only spawned if validator found failures*. Gets ONLY the
   failure list + relevant file paths (not full context) → fixes them. Then re-run validator.
   Loop until green or 2–3 attempts, then escalate to me/user.

**Token discipline:**
- Subagents read the plan file for context (single source of truth) — I don't re-paste it.
- Validator returns only failures, not full logs.
- Repair agent gets scoped failure list + file paths only, not whole repo.
- If validator returns all-green → skip repair entirely (no wasted spawn).
- Reuse the same builder agent via follow-up where context helps; fresh agents where clean slate
  is cheaper.

I gate between phases: Phase 2 builder only launches after Phase 1 is green.

---

## Architecture

```
User ─► Chainlit UI ─► FastAPI /chat
                          │
                   Input Guardrails (validate, prompt-injection, PII mask)
                          │
                   Semantic Cache check (hit → return)
                          │
                   Model Router (pick gpt-4o-mini vs gpt-4o)
                          │
                   LangGraph Agent
                     ├─ Hybrid Retrieval tool ─► Vector (Chroma) + Graph (Neo4j) ─► Re-rank
                     ├─ Web search tool
                     ├─ SQL query tool
                     └─ Python exec tool
                          │
                   LLM generate (cite sources)
                          │
                   Output Guardrails (hallucination check, PII, toxicity filter)
                          │
                   Langfuse trace (latency, tokens, errors) ─► Response + citations
```

## Tech Stack

- **Backend**: FastAPI, Python 3.11, uvicorn
- **Frontend**: Chainlit (separate process, calls FastAPI; or Chainlit-native + shared pipeline module)
- **Vector DB**: ChromaDB (local persistent)
- **Graph DB**: Neo4j (Docker container, `neo4j` python driver)
- **Embeddings**: OpenAI `text-embedding-3-small`
- **LLM**: OpenAI `gpt-4o-mini` / `gpt-4o`
- **Agent**: LangGraph + LangChain tools
- **Re-ranking**: `sentence-transformers` cross-encoder (`ms-marco-MiniLM`) or Cohere rerank
- **Guardrails**: Presidio (PII), custom prompt-injection regex/classifier, LLM-judge hallucination check
- **Observability**: Langfuse (cloud free tier or self-host)
- **Semantic cache**: GPTCache or Redis + embedding similarity
- **Evals**: Promptfoo (Node), RAGAS (Python)
- **Orchestration**: docker-compose (Neo4j, Redis, app)

---

## Data: what goes in Vector vs Graph (+ we generate it ourselves)

**No real corpus exists → we GENERATE dummy enterprise data as part of the build** (spec allows
dummy data). Both stores are fed from the SAME generated corpus.

**ChromaDB (vector)** = unstructured TEXT chunks for semantic search ("what does it say").
- Policy PDFs, technical manuals, SOPs, incident reports, FAQ/KB articles → chunked + embedded
- Each chunk metadata: `{source, doc_type, dept, date, chunk_id}`

**Neo4j (graph)** = ENTITIES + RELATIONSHIPS for multi-hop reasoning ("how does X relate to Y").
- Nodes: people, systems, components, services, teams
- Edges: `depends_on`, `owns`, `related_to`, `manages`
- Extracted from same docs via LLM; CSV rows also seed nodes.

### Worked example (one generated doc → both stores)

Generated incident report `INC-204.md`:
> "On 2026-03-12 the Payment-Service outage was caused by Auth-DB hitting connection limits.
> Payment-Service depends on Auth-DB. The Billing team, led by Priya Sharma, owns Payment-Service
> and restored it per SOP-17."

→ **Chroma** gets: text chunks of that report + metadata `{source: INC-204, doc_type: incident,
dept: ops}`. Answers "what caused the March payment outage?"

→ **Neo4j** gets nodes/edges:
```
(Payment-Service)-[:DEPENDS_ON]->(Auth-DB)
(Billing-Team)-[:OWNS]->(Payment-Service)
(Priya-Sharma)-[:MANAGES]->(Billing-Team)
(Payment-Service)-[:RESOLVED_BY]->(SOP-17)
```
Answers "if Payment-Service breaks, what else fails and who do I call?" → multi-hop traversal.

### Fake-data generator (new build artifact)

`ingestion/generate_fake_data.py` — uses LLM (+ Faker) to produce a coherent corpus where docs,
entities, and relations cross-reference each other (so multi-hop queries actually have answers):
- ~15–20 docs: policies (PDF via reportlab), manuals/SOPs (md), incident reports (md), FAQ (md)
- CSVs: products, users, transactions, metadata tables
- A consistent entity/relation set woven THROUGH the docs (shared system/team/person names) so
  graph extraction finds real connections, not isolated nodes.
Output → `data/raw/`. Then T2 loads → Chroma, T3 extracts → Neo4j.

---

## Project Structure

```
app/
  main.py                 # FastAPI app, /chat /health endpoints, session handling
  chainlit_app.py         # Chainlit UI entrypoint (on_message → pipeline)
  config.py               # env/settings (pydantic-settings)
  pipeline.py             # orchestrates: guardrails→cache→router→agent→guardrails→trace
  ingestion/
    generate_fake_data.py # LLM+Faker → coherent dummy corpus (docs+CSVs) w/ cross-refs
    loader.py             # load PDF/md/txt/csv, clean, extract metadata
    chunker.py            # chunk + embed → Chroma
    graph_builder.py      # entity/relation extraction → Neo4j
  retrieval/
    vector_search.py      # Chroma query
    graph_search.py       # Neo4j Cypher traversal
    hybrid.py             # merge + rerank
  agent/
    graph.py              # LangGraph state machine
    tools.py              # web_search, sql_query, python_exec, retrieve
  guardrails/
    input_guards.py       # validation, injection detect, PII mask
    output_guards.py      # hallucination check, PII, toxicity filter
  observability/
    tracing.py            # Langfuse wrappers
  caching/
    semantic_cache.py     # embedding-similarity cache
  routing/
    model_router.py       # complexity → model choice
data/
  raw/                    # dummy corpus (PDFs, md, csv)
  processed/
  chroma_db/
eval/
  promptfooconfig.yaml    # 30+ test cases
  ragas_eval.py           # faithfulness, answer relevance, ctx precision/recall
  safety_eval.py          # adversarial prompts → safety scorecard
  load_test.py            # locust/latency throughput
docs/
  ARCHITECTURE.md
  SOLUTION.md             # overview, approach, stepwise walkthrough
  SAFETY_SCORECARD.md
  RAGAS_REPORT.md
docker-compose.yml
requirements.txt
.env.example
README.md
```

---

## Plan Storage

First action of Phase 1 = copy this plan into the repo as `docs/SOLUTION.md` (and keep building
it into the walkthrough doc). So plan lives WITH the code, not just in `.claude/plans/`.

---

## Environment Variables — keys needed + how to get them

`.env` keys required. For each: I will either (a) give you exact click-steps, or (b) **drive your
browser to generate it** if you say go. Paste each key into `.env` (template = `.env.example`).

| Key | Service | Free? | How to generate |
|---|---|---|---|
| `OPENAI_API_KEY` | OpenAI | Paid (low cost) | platform.openai.com → log in → **API keys** → *Create new secret key* → copy. Add ~$5 credit under Billing. |
| `LANGFUSE_PUBLIC_KEY` + `LANGFUSE_SECRET_KEY` + `LANGFUSE_HOST` | Langfuse | Free tier | cloud.langfuse.com → sign up → **New project** → *Settings → API Keys → Create*. Host = `https://cloud.langfuse.com`. |
| `NEO4J_URI` + `NEO4J_USER` + `NEO4J_PASSWORD` | Neo4j | Free | Local Docker (compose sets `neo4j/password`) → URI `bolt://localhost:7687`. OR Neo4j Aura free cloud → copy connection creds. |
| `TAVILY_API_KEY` (web search tool) | Tavily | Free tier | tavily.com → sign up → dashboard → copy key. (Fallback: DuckDuckGo, no key.) |
| `COHERE_API_KEY` (optional rerank) | Cohere | Free trial | dashboard.cohere.com → API keys. *Optional* — default rerank = local cross-encoder, no key. |

**Redis** (semantic cache) = no key, runs via Docker compose.

During build I will pause at T0, list each missing key, and offer: *"paste it"* or *"want me to
open the browser and walk through generating it?"* (browser control needs your login/2FA, so you
stay in the loop).

---

## Build Steps (maps to spec TASK 0–13)

### PHASE 1 — Working Vertical Slice (get a real answer end-to-end FIRST)

Goal: smallest path that returns a cited answer in the Chainlit UI. Proves the spine before
piling on graph/guardrails/evals.

- **T0 Setup** — venv, `requirements.txt`, `.env.example`, folder skeleton, git init.
  Collect/generate API keys (OpenAI, Langfuse minimum). docker-compose for Redis + Neo4j.
- **T1 Generate + Ingest** — run `generate_fake_data.py` → coherent dummy corpus (cross-
  referenced docs + CSVs) into `data/raw/`. Then load/clean/metadata. This is the data both
  Chroma and Neo4j consume.
- **T2 Vector index** — chunk + embed → ChromaDB. Validate top-k retrieval.
- **T7 FastAPI (minimal)** — `/chat` + `/health`, vector-only RAG, return answer + citations.
- **Chainlit UI** — `on_message` → `/chat`, render answer + sources + step trace.
- **T8 Langfuse (basic)** — trace the pipeline, confirm traces appear.

✅ **Phase 1 validation gate** (must pass before Phase 2):
1. `curl /health` → 200
2. `curl /chat` w/ sample query → answer + ≥1 citation + trace_id
3. Chainlit UI loads, query returns cited answer
4. Langfuse shows the trace w/ latency + tokens

### PHASE 2 — Full Production Features + Evals

Builds on the working slice. Each task additive, re-run Phase 1 gate after each.

- **T3 Graph** — entity/relation extraction → Neo4j, validate Cypher.
- **T4 Hybrid retrieval** — vector + graph merge + cross-encoder rerank.
- **T5 LangGraph agent** — state machine + tools (retrieve, web_search, sql_query, python_exec).
- **T6 Guardrails** — input (validate, injection, PII mask) + output (hallucination, PII, toxicity).
- **Routing + semantic cache** — model router (mini vs 4o), Redis embedding cache.
- **T9 Promptfoo** — 30+ cases + regression run.
- **T10 RAGAS** — faithfulness, answer relevance, ctx precision/recall → report.
- **T11 Safety** — adversarial set → safety scorecard.
- **T12 Perf** — cache hit-rate, latency p50/p95, throughput (locust).
- **T13 Deploy + docs** — ARCHITECTURE.md, SOLUTION.md, README, push GitHub, walkthrough.

---

## ORIGINAL TASK NOTES (detail per task, unchanged)

**T0 Setup** — venv, `requirements.txt`, `.env.example` (OPENAI_API_KEY, NEO4J_*, LANGFUSE_*),
docker-compose (Neo4j + Redis), folder skeleton. Init git repo.

**T1 Ingestion** — `ingestion/loader.py`: load dummy corpus (generate ~15-20 fake enterprise
docs: policies PDF, SOPs md, FAQ, incident reports + products/users/transactions CSV). Clean,
normalize, attach metadata (source, type, date, dept).

**T2 Vector index** — `chunker.py`: recursive chunk (~500 tok, 50 overlap), embed
`text-embedding-3-small`, persist Chroma. Validation script: sample query → check top-k.

**T3 Graph** — `graph_builder.py`: LLM-based entity/relation extraction (people, systems,
components; depends_on/owns/related_to). Load Neo4j. Validate w/ Cypher queries.

**T4 Hybrid retrieval** — `hybrid.py`: parallel vector search + graph traversal, merge
(dedup + weighted score), cross-encoder rerank top-N. Return chunks + sources.

**T5 LangGraph agent** — `agent/graph.py`: state machine (plan → tool-select → execute →
synthesize). Tools: `retrieve` (hybrid), `web_search` (Tavily/DuckDuckGo free), `sql_query`
(read-only sqlite over CSVs), `python_exec` (sandboxed). Multi-step reasoning loop.

**T6 Guardrails** — input: length/format validation, prompt-injection detection (regex +
heuristics), Presidio PII detect+mask. output: hallucination check (LLM judge: answer grounded
in retrieved ctx?), PII re-scan, toxicity/output filter. Block or redact.

**T7 FastAPI** — `/chat` (session_id, message → structured resp w/ answer, citations, trace_id,
latency), `/health`. Wire full `pipeline.py`. In-memory session store.

**T8 Langfuse** — `tracing.py`: decorate pipeline stages, capture latency, token usage, model,
cache hit/miss, errors. Screenshot traces for deliverable.

**T9 Promptfoo** — `promptfooconfig.yaml`: 30+ cases (factual Q&A, multi-hop, citation present,
injection refused, PII masked, out-of-scope handled). Assertions + regression run.

**T10 RAGAS** — `ragas_eval.py`: eval dataset of test queries → faithfulness, answer relevance,
context precision, context recall. Output `RAGAS_REPORT.md`.

**T11 Safety** — `safety_eval.py`: adversarial prompt set (jailbreaks, PII extraction, injection,
toxic). Measure block rate → `SAFETY_SCORECARD.md`.

**T12 Perf** — semantic cache hit-rate test, latency p50/p95, throughput (locust). Verify
`routing/model_router.py` saves cost.

**T13 Deploy + docs** — finalize structure, write ARCHITECTURE.md + SOLUTION.md, README run
instructions, push to GitHub. Walkthrough doc covering 8 spec points.

---

## Chainlit Frontend Detail

`chainlit_app.py`:
- `@cl.on_chat_start` → init session
- `@cl.on_message` → POST to FastAPI `/chat` (or call `pipeline` directly)
- Stream answer via `cl.Message`
- Render citations as `cl.Text`/source elements
- Use `cl.Step` to visualize agent tool calls + retrieval (native step trace = great demo)
- Show latency + Langfuse trace link in message footer

Run: `chainlit run app/chainlit_app.py` (port 8000) alongside `uvicorn app.main:app` (8001).

---

## FINAL Validation — full system health check (run at very end)

A scripted `validate.py` (+ manual UI checks) confirming EVERYTHING works. Build this as a real
script so it's repeatable, not a one-off.

**A. Env + service preflight** (`validate.py` step 1)
- Assert every required env var present + non-empty (OPENAI, LANGFUSE_*, NEO4J_*, TAVILY). Fail
  loud listing which are missing → tell user exactly which key to generate.
- Ping each service: OpenAI (cheap models.list), Langfuse (auth check), Neo4j (driver verify),
  Redis (ping). Print ✅/❌ per service.

**B. Pipeline checks** (`validate.py` step 2)
- `docker-compose up` → Neo4j browser :7474 reachable
- Ingestion ran → Chroma persisted (count > 0) + Neo4j has nodes/edges (Cypher count)
- `/health` → 200
- `/chat` sample query → answer + ≥1 citation + trace_id
- Multi-hop query → graph path used in answer
- Injection prompt → refused; PII input → masked in response
- Cache: same query twice → 2nd is cache hit (faster, flagged)

**C. UI check** (manual)
- `chainlit run` → multi-hop query → sources + step trace render; trace link + latency shown

**D. Deliverable evals**
- `promptfoo eval` → 30+ cases, record pass rate
- `python eval/ragas_eval.py` → metrics → RAGAS_REPORT.md
- `python eval/safety_eval.py` → safety scorecard
- `locust` → p50/p95 + throughput
- Langfuse → traces w/ latency + tokens present → screenshot for deliverable

`validate.py` prints a final ✅/❌ summary table. Green across = capstone done.

---

## Open Notes / Risks

- Neo4j needs Docker Desktop running on Windows. Fallback: Neo4j Aura free cloud tier.
- `python_exec` tool = sandbox carefully (restrict imports, timeout) — security item.
- OpenAI cost: keep gpt-4o-mini default; gpt-4o only on router-flagged hard queries.
- Promptfoo needs Node.js installed.
- Build incrementally — get T1→T2→T7→frontend working (vertical slice) BEFORE adding graph,
  guardrails, evals. Avoids big-bang integration pain.
