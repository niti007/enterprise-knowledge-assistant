# V2 — Teaching Course Plan (approved)

> The second approved plan: designing the 19-chapter beginner course under `docs/course/`.
> Reproduced verbatim from the conversation's second approved-plan block.

---

# Plan: Full Teaching Course for the Enterprise Knowledge Assistant

## Context

The project is built, deployed, and on GitHub (niti007/enterprise-knowledge-assistant).
The user will **teach this project to students** and needs a complete, follow-along course:
from installing tools → getting every API key (with links) → building/running each module in
order → **line-by-line code explanation in plain words (no jargon)** → why each technology is
used (e.g. "why FastAPI, what's the need") → testing → deployment.

**Decisions (from user):**
- **Format:** a numbered **multi-part course folder** at `docs/course/` (one chapter per file, so
  each can be a class).
- **Code depth:** explain **every meaningful line**; group trivial imports/boilerplate in a one-liner.
- **Audience:** **complete beginners** — explain what a terminal, virtual environment, API key,
  environment variable, embedding, vector DB, graph DB, agent, etc. even are, with short
  "new term" callouts.

Every chapter must say **what** the code does, **why** it's there, and **why we chose that
technology** (what would break/why it's needed). Chapters are ordered as the **build/run order**,
so "start with chapter 03, then 04…" is literally the order to construct and run the app.

## Where things live (source of truth for the writers)

All code already read and understood. Key files to explain, in build order:
- `app/config.py` — settings from `.env`
- `app/ingestion/generate_fake_data.py`, `loader.py`, `chunker.py`
- `app/retrieval/embeddings.py`, `vector_search.py`, `graph_search.py`, `hybrid.py`
- `app/ingestion/graph_builder.py`
- `app/agent/graph.py`, `app/agent/tools.py`
- `app/guardrails/input_guards.py`, `output_guards.py`
- `app/routing/model_router.py`, `app/caching/semantic_cache.py`
- `app/observability/tracing.py`
- `app/pipeline.py` (the assembly line — ties everything)
- `app/main.py` (FastAPI), `app/chainlit_app.py` (UI)
- `eval/*` (promptfoo, ragas, safety, load)
Supporting docs to link/reuse: `docs/ARCHITECTURE.md`, `docs/PROJECT_GUIDE.md`,
`data/raw/raw_data_explanation.md`, `README.md`, `.env.example`.

## Deliverable: `docs/course/` chapters

```
docs/course/
  README.md                 # course index, how to use, suggested class schedule, prerequisites list
  00-what-and-why.md        # the problem; the big-picture analogy; WHY each tech (FastAPI, ChromaDB,
                            #   Neo4j, OpenRouter, local embeddings, LangGraph, guardrails, Chainlit,
                            #   Langfuse, semantic cache) — each: what is it / why needed / what breaks without it
  01-tools-and-accounts.md  # install Python 3.12, VS Code, Git, Node.js (with official links);
                            #   create accounts + GET KEYS step-by-step w/ links: OpenRouter, Neo4j Aura,
                            #   Langfuse, (optional Tavily). What an "API key" is.
  02-project-setup.md       # make folder, open in VS Code, what a virtual env is + create/activate it,
                            #   folder structure, requirements.txt (what each dep is, plainly),
                            #   pip install, spaCy model, create .env from .env.example, paste keys.
                            #   What an "environment variable" is and why keys go in .env (never in code).
  03-config.md              # config.py — line by line; why one central settings file
  04-generate-data.md       # generate_fake_data.py; what the dataset is (link raw_data_explanation.md)
  05-embeddings-vector.md   # embeddings.py + chunker.py + vector_search.py; what embeddings/chunking/vector DB are
  06-knowledge-graph.md     # graph_builder.py + graph_search.py; what a graph DB is; Cypher basics
  07-hybrid-retrieval.md    # hybrid.py; merging + what a re-ranker is and why
  08-agent-and-tools.md     # agent/graph.py + tools.py; what an "agent" is; LangGraph; the 4 tools + safety
  09-guardrails.md          # input_guards.py + output_guards.py; injection, PII, hallucination — plainly
  10-routing-and-cache.md   # model_router.py + semantic_cache.py; saving money + speed
  11-observability.md       # tracing.py; what Langfuse shows and why you need it
  12-pipeline.md            # pipeline.py; the full assembly line, step by step (the "aha" chapter)
  13-api-fastapi.md         # main.py; WHAT an API is, WHY FastAPI (the need), the two endpoints
  14-frontend-chainlit.md   # chainlit_app.py; why Chainlit; how it shows steps + sources
  15-run-it.md              # exact build+run order, first-run cold start, troubleshooting table
  16-testing-evaluation.md  # promptfoo/ragas/safety/load — what each proves, how to read the numbers
  17-deployment.md          # Hugging Face Spaces deploy, secrets, GitHub
  18-teacher-notes.md       # talking points, FAQs students will ask, the real bug stories, class schedule
```

## Style rules (every chapter)

- Plain English, no unexplained jargon. First use of any term → a short **"🔑 New word:"** callout.
- For code: show a short snippet, then a bullet per meaningful line: **what** it does + **why**.
- Group trivial lines (imports/`from __future__`) in a single one-liner.
- Each tech chapter opens with a **"Why this / what's the need"** box and a real-world analogy.
- End each chapter with: **"✅ You just built/learned…"**, **"▶️ Run this now:"** (exact command),
  and **"🧠 Check yourself"** (2–3 simple questions).
- Cross-link chapters ("continue to 06-knowledge-graph.md").
- Keep line references accurate to the current code (writers must open the real file, not guess).

## Execution approach (how we'll build it — token-aware)

Orchestrator (Opus) writes the **conceptual + setup chapters** (README, 00, 01, 02, 15, 16, 17, 18)
directly, since they need whole-project judgment. The **line-by-line code chapters** (03–14) are
split across **2–3 Sonnet subagents in parallel**, each assigned a specific batch of chapters +
the exact files to open and explain, following the Style rules above. Each subagent returns the
finished chapter files. Orchestrator reviews for accuracy against the code, fixes cross-links, and
assembles `README.md` index.

Rationale: chapters are independent (one file each), so parallel writing is safe and fast; giving
each subagent the precise file list keeps them accurate and cheap.

## Verification

- Every chapter file exists under `docs/course/` and is non-empty.
- Spot-check 3–4 code chapters against the real source files: the snippets quoted must match the
  actual code (open the file, compare).
- Every run command in the chapters matches the real module paths (e.g.
  `python -m app.ingestion.chunker`, `chainlit run app/chainlit_app.py --port 8000`).
- All external links resolve to the right place (python.org, code.visualstudio.com,
  openrouter.ai/keys, console.neo4j.io, cloud.langfuse.com, nodejs.org, git-scm.com).
- `README.md` index links to every chapter in order.
- Final: commit + push `docs/course/` to GitHub (public repo), confirm `.env` never staged.

## Out of scope
- No code changes to the app itself — this is documentation only.
- No screenshots captured programmatically (describe where to click; user can add screenshots).
