# 🎓 Build an AI Knowledge Assistant — Full Course

A complete, follow-along course that teaches you to build a **production-style AI system**
from scratch: an assistant that answers questions from company documents, shows its sources,
connects facts across documents, stays safe, and runs on the internet.

Written for **complete beginners** — every technical word is explained the first time it
appears, and every meaningful line of code is explained in plain English (what it does + why).

> **Live demo:** https://Nitishgalat-enterprise-knowledge-assistant.hf.space
> **Code:** https://github.com/niti007/enterprise-knowledge-assistant

---

## How to use this course
- Read the chapters **in order** — each builds on the last, and the order is also the order
  you build and run the app.
- Every chapter ends with **✅ You just learned**, **▶️ Run this now**, and **🧠 Check yourself**.
- Watch for **🔑 New word** callouts — they define a term in one plain sentence.
- Teaching a class? See **[Chapter 18 — Teacher Notes](18-teacher-notes.md)** for a schedule,
  demo tips, and student exercises.

## What you'll need (details in Chapter 01)
- A computer (Windows steps shown), ~2 hours for setup, and free accounts for OpenRouter
  (AI), Neo4j Aura (graph database), and optionally Langfuse (monitoring).

---

## Table of contents

### Part 1 — Understand & Set Up
- **[00 — What We're Building and Why](00-what-and-why.md)** — the problem, the big picture,
  and *why* each technology (no coding).
- **[01 — Install the Tools & Get Your Keys](01-tools-and-accounts.md)** — Python, VS Code,
  Git, Node.js + all API keys, with links.
- **[02 — Set Up the Project](02-project-setup.md)** — download the code, virtual environment,
  install libraries, create your `.env`.

### Part 2 — Build the Pieces (line-by-line code)
- **[03 — Settings (`config.py`)](03-config.md)** — one central place for all configuration.
- **[04 — Making the Sample Data](04-generate-data.md)** — the fake company documents.
- **[05 — Embeddings & the Vector Database](05-embeddings-vector.md)** — search by *meaning*.
- **[06 — The Knowledge Graph](06-knowledge-graph.md)** — search by *connections* (Neo4j).
- **[07 — Hybrid Retrieval & Re-ranking](07-hybrid-retrieval.md)** — combine both, keep the best.
- **[08 — The Agent & Its Tools](08-agent-and-tools.md)** — let the AI decide and act (LangGraph).
- **[09 — Guardrails (Safety)](09-guardrails.md)** — block attacks, hide private data, catch made-up answers.
- **[10 — Model Routing & Semantic Cache](10-routing-and-cache.md)** — save money and time.
- **[11 — Observability (Langfuse)](11-observability.md)** — see inside every request.

### Part 3 — Wire It Together & Ship
- **[12 — The Pipeline](12-pipeline.md)** — the assembly line that connects everything. *(the "aha")*
- **[13 — The API (FastAPI)](13-api-fastapi.md)** — the clean front door.
- **[14 — The Chat UI (Chainlit)](14-frontend-chainlit.md)** — the face users talk to.
- **[15 — Build It and Run It](15-run-it.md)** — the exact order + troubleshooting.
- **[16 — Testing & Evaluation](16-testing-evaluation.md)** — prove it works with numbers.
- **[17 — Put It Online (Deployment)](17-deployment.md)** — Hugging Face Spaces.

### For Instructors
- **[18 — Teacher Notes](18-teacher-notes.md)** — schedule, FAQs, demo tips, debugging stories.

---

## The finished system, in one picture

```
You ask a question
   → Safety check (in)  → Cache  → Router  → Agent (search docs + graph + tools)
   → AI writes a cited answer  → Safety check (out)  → Recording (Langfuse)
   → Answer + sources
```

By the end you'll have built every box above — and understand exactly why each one is there.

Start here → **[00 — What We're Building and Why](00-what-and-why.md)**

---

## Companion docs (already in this repo)
- [../PROJECT_GUIDE.md](../PROJECT_GUIDE.md) — compact plain-English walkthrough of the whole system.
- [../ARCHITECTURE.md](../ARCHITECTURE.md) — architecture diagram + component table.
- [../../data/raw/raw_data_explanation.md](../../data/raw/raw_data_explanation.md) — what the sample data is and how it connects.
