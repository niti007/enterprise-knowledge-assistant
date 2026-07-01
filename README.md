# Enterprise Knowledge Assistant

Production-grade AI Knowledge Assistant with **hybrid RAG (vector + graph)**, a
**LangGraph agent** with tools, **multi-layer guardrails**, **FastAPI** serving,
**Langfuse** observability, **semantic caching**, and **model routing**.

**Tech stack:** FastAPI · Chainlit · ChromaDB (local embeddings) · Neo4j Aura ·
OpenRouter (OpenAI-compatible LLM) · Langfuse · LangGraph · sentence-transformers ·
Presidio · fakeredis · Promptfoo · RAGAS

> **LLM = OpenRouter** (`openai/gpt-4o-mini` default, `openai/gpt-4o` for hard
> queries). **Embeddings run locally** (ChromaDB ONNX MiniLM) — no paid embedding
> API. **Graph = Neo4j Aura** free cloud (no Docker needed).

---

## Prerequisites
- Python 3.12 (3.11+ works)
- Node.js 18+ (for Promptfoo evals)
- An OpenRouter API key — https://openrouter.ai/keys
- A Neo4j Aura free instance — https://console.neo4j.io (or local Neo4j via Docker)
- (Optional) Langfuse cloud keys — https://cloud.langfuse.com

---

## Setup

### 1. Virtual environment + dependencies
```powershell
py -3.12 -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m spacy download en_core_web_sm   # for Presidio PII
```

### 2. Configure `.env`
```powershell
Copy-Item .env.example .env
```
Fill in (see `.env.example` for the full annotated list):
```
OPENAI_API_KEY=sk-or-v1-...            # OpenRouter key
OPENAI_BASE_URL=https://openrouter.ai/api/v1
EMBEDDING_PROVIDER=local
LLM_DEFAULT_MODEL=openai/gpt-4o-mini
LLM_ADVANCED_MODEL=openai/gpt-4o
NEO4J_URI=neo4j+s://<id>.databases.neo4j.io
NEO4J_USER=neo4j
NEO4J_PASSWORD=...
LANGFUSE_PUBLIC_KEY=pk-lf-...          # optional (traces degrade to no-op)
LANGFUSE_SECRET_KEY=sk-lf-...
```

### 3. Generate the corpus + build the indexes
```powershell
python -m app.ingestion.generate_fake_data   # ~25 cross-referenced docs + CSVs (Faker, no key)
python -m app.ingestion.chunker               # chunk + LOCAL-embed → ChromaDB (data/chroma_db)
python -m app.ingestion.graph_builder         # LLM entity/relation extraction → Neo4j Aura
```

### 4. Run the app
```powershell
# Terminal 1 — API
uvicorn app.main:app --host 127.0.0.1 --port 8001
# Terminal 2 — UI
chainlit run app/chainlit_app.py --port 8000


> First request is a cold start (~1–2 min: loads Presidio/spaCy/ONNX/CrossEncoder).
> Subsequent queries are ~6–10s; cache hits ~0.6s.


```

---

## Evaluation & Safety

```powershell
# Promptfoo — 31 RAG-quality + safety cases (API must be running)
cd eval; npx -y promptfoo@latest eval -c promptfooconfig.yaml; cd ..

# Safety scorecard (adversarial battery) → docs/SAFETY_SCORECARD.md
python -m eval.safety_eval

# Load / performance test → docs/LOAD_TEST_REPORT.md
python -m eval.load_test

# RAGAS (isolated venv, protects app langchain) → docs/RAGAS_REPORT.md
py -3.12 -m venv .venv-eval
.venv-eval\Scripts\python.exe -m pip install ragas==0.2.15 langchain-openai langchain-huggingface sentence-transformers datasets requests
.venv-eval\Scripts\python.exe -m eval.ragas_eval
```

Generated reports live in `docs/`:
- `SAFETY_SCORECARD.md` — adversarial safe-handling rate (injection, PII, exfiltration, harmful, hallucination-bait)
- `RAGAS_REPORT.md` — faithfulness, answer relevancy, context precision/recall
- `LOAD_TEST_REPORT.md` — latency p50/p95 + semantic-cache speedup

---

## Observability (Langfuse)

Every `/chat` request emits a trace (pipeline spans: input guards → cache → router →
agent tools → output guards) with latency + token usage at
`https://cloud.langfuse.com` → your project → **Traces**. Capture screenshots there
for the observability deliverable.

---

## Project Structure

```
app/
  main.py              # FastAPI: /health, /chat
  chainlit_app.py      # Chainlit UI (agent step trace + citations)
  config.py            # pydantic-settings (OpenRouter base_url, Neo4j, etc.)
  pipeline.py          # guards → cache → router → agent → guards → trace
  ingestion/           # generate_fake_data, loader, chunker, graph_builder
  retrieval/           # embeddings (local ONNX), vector_search, graph_search, hybrid (+rerank)
  agent/               # LangGraph graph + tools (retrieve, web_search, sql_query, python_exec)
  guardrails/          # input_guards (injection, PII), output_guards (hallucination, PII, toxicity)
  caching/             # semantic_cache (fakeredis + local embeddings)
  routing/             # model_router (complexity → model)
  observability/       # tracing (Langfuse)
data/raw, data/chroma_db
eval/  promptfooconfig.yaml, ragas_eval.py, safety_eval.py, load_test.py
docs/  ARCHITECTURE.md, SOLUTION.md, *_REPORT / SCORECARD
validate.py            # end-to-end health check
```

See `docs/ARCHITECTURE.md` for the full architecture and `docs/SOLUTION.md` for the
build plan / walkthrough.
