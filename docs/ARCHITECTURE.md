# Architecture — Enterprise Knowledge Assistant

Production-style, hybrid-RAG knowledge assistant with an agentic tool loop,
multi-layered guardrails, observability, semantic caching, and model routing.

## System Diagram

```
User ─► Chainlit UI (port 8000)
            │  POST /chat
            ▼
       FastAPI (port 8001)  — app/main.py
            │
     ┌──────▼─────────────────────────────────────────────┐
     │  pipeline.py  (Pipeline.run)                         │
     │                                                     │
     │  1. Input Guards   — validation, prompt-injection,  │
     │                      Presidio PII detect + mask     │
     │  2. Semantic Cache — fakeredis + local embedding    │
     │                      cosine match (hit → return)    │
     │  3. Model Router   — gpt-4o-mini (default) /        │
     │                      gpt-4o (multi-hop / complex)   │
     │  4. LangGraph Agent (ReAct tool loop)               │
     │       ├─ retrieve   → Hybrid Retrieval:             │
     │       │     ChromaDB (vector, local ONNX embed)     │
     │       │   + Neo4j Aura (graph traversal)            │
     │       │   → merge/dedup → CrossEncoder re-rank      │
     │       ├─ web_search (Tavily, optional)              │
     │       ├─ sql_query  (read-only SQLite over CSVs)    │
     │       └─ python_exec (sandboxed calc)               │
     │  5. LLM synthesize (OpenRouter) + inline citations  │
     │  6. Output Guards  — hallucination (LLM judge),     │
     │                      PII re-scan, toxicity filter   │
     │  7. Langfuse trace — latency, tokens, spans         │
     └─────────────────────────────────────────────────────┘
```

## Key design decisions

- **LLM via OpenRouter** (OpenAI-compatible). `gpt-4o` family is used because
  its standard Chat-Completions tool-calling works reliably with LangGraph
  (the `gpt-4.1` family routes via the Responses API and breaks the tool
  round-trip).
- **Local embeddings** (ChromaDB `ONNXMiniLM_L6_V2`) — OpenRouter has no
  embeddings endpoint, so vectorization runs on-device (no paid embedding API).
- **Neo4j Aura (cloud free tier)** for the knowledge graph — no local Docker
  required.
- **Semantic cache** on `fakeredis` (in-process) — repeated/similar queries
  return in ~0.6s instead of ~8s.
- **Graceful degradation** — missing optional keys (Tavily, Cohere, Langfuse)
  disable that feature instead of crashing; agent errors fall back to vector RAG.

## Components

| Component | Tech | Path |
|-----------|------|------|
| API server | FastAPI + uvicorn | `app/main.py` |
| Chat UI | Chainlit | `app/chainlit_app.py` |
| Settings | pydantic-settings | `app/config.py` |
| Orchestration | Python | `app/pipeline.py` |
| Data generation | Faker + reportlab | `app/ingestion/generate_fake_data.py` |
| Document loader | PyMuPDF + csv | `app/ingestion/loader.py` |
| Chunk + index | tiktoken + ChromaDB | `app/ingestion/chunker.py` |
| Embeddings (shared) | ChromaDB ONNX MiniLM (local) | `app/retrieval/embeddings.py` |
| Vector search | ChromaDB | `app/retrieval/vector_search.py` |
| Graph build | Neo4j Aura + LLM extraction | `app/ingestion/graph_builder.py` |
| Graph search | Neo4j Cypher | `app/retrieval/graph_search.py` |
| Hybrid retrieval + rerank | sentence-transformers CrossEncoder | `app/retrieval/hybrid.py` |
| Agent | LangGraph (ReAct) | `app/agent/graph.py`, `app/agent/tools.py` |
| Input guardrails | Presidio + regex heuristics | `app/guardrails/input_guards.py` |
| Output guardrails | LLM-judge + PII + toxicity | `app/guardrails/output_guards.py` |
| Semantic cache | fakeredis + local embeddings | `app/caching/semantic_cache.py` |
| Model router | heuristic complexity scoring | `app/routing/model_router.py` |
| Observability | Langfuse | `app/observability/tracing.py` |

## Data: vector vs graph

- **ChromaDB (vector)** — text chunks of policies, SOPs, manuals, incident
  reports, FAQ; answers "what does it say" (semantic search). 46 chunks.
- **Neo4j Aura (graph)** — entities (people, systems, teams) + relations
  (`DEPENDS_ON`, `OWNS`, `MANAGES`, `RESOLVED_BY`, `RELATED_TO`); answers
  "how does X relate to Y" (multi-hop). ~120 nodes / ~280 edges.

Both are built from the SAME generated corpus in `data/raw/`.

## Retrieval → agent flow

1. `generate_fake_data.py` writes ~25 cross-referenced docs + CSVs to `data/raw/`.
2. `chunker.py` → chunk → local-embed → persist `data/chroma_db/`.
3. `graph_builder.py` → LLM entity/relation extraction → Neo4j Aura.
4. `POST /chat` → guards → cache → router → agent.
5. Agent `retrieve` tool runs hybrid search: vector top-k + graph facts →
   merge → CrossEncoder re-rank → passages returned to the LLM.
6. LLM synthesizes a cited answer; output guards verify grounding; Langfuse traces.

## Evaluation & safety

- **Promptfoo** — `eval/promptfooconfig.yaml` (31 cases) against `/chat`.
- **RAGAS** — `eval/ragas_eval.py`: faithfulness, answer relevancy, context
  precision/recall (OpenRouter judge + local embeddings) → `docs/RAGAS_REPORT.md`.
- **Safety** — `eval/safety_eval.py`: adversarial battery → `docs/SAFETY_SCORECARD.md`.
- **Load** — `eval/load_test.py`: latency p50/p95 + cache speedup → `docs/LOAD_TEST_REPORT.md`.

## Ports

- FastAPI: `http://localhost:8001`  (`/chat`, `/health`)
- Chainlit: `http://localhost:8000`
- Neo4j: Neo4j Aura cloud (`neo4j+s://…databases.neo4j.io`)
- Semantic cache: in-process (fakeredis)
