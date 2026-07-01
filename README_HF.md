---
title: Enterprise Knowledge Assistant
emoji: 🧠
colorFrom: indigo
colorTo: blue
sdk: docker
app_port: 7860
pinned: false
short_description: Hybrid RAG + agent + guardrails knowledge assistant
---

# Enterprise Knowledge Assistant

Production-style GenAI assistant: **hybrid RAG** (ChromaDB vector + Neo4j graph +
CrossEncoder rerank), a **LangGraph agent** with tools, **multi-layer guardrails**
(prompt-injection, PII masking, hallucination/toxicity checks), **Langfuse** tracing,
**semantic caching**, and **model routing** via OpenRouter.

Chat UI built with Chainlit. The vector index is rebuilt at startup from the baked-in
corpus (local embeddings); the knowledge graph is read from Neo4j Aura.

**Required Space secrets** (Settings → Variables and secrets):
`OPENAI_API_KEY` (OpenRouter key), `OPENAI_BASE_URL`, `EMBEDDING_PROVIDER=local`,
`LLM_DEFAULT_MODEL`, `LLM_ADVANCED_MODEL`, `NEO4J_URI`, `NEO4J_USER`, `NEO4J_PASSWORD`,
`NEO4J_DATABASE`, and optional `LANGFUSE_PUBLIC_KEY` / `LANGFUSE_SECRET_KEY` / `LANGFUSE_HOST`.

Source: https://github.com/niti007/enterprise-knowledge-assistant
