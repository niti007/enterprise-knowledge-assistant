#!/usr/bin/env bash
# HF Space startup: build the vector index from the baked-in corpus if missing,
# then launch Chainlit on the HF-expected port (7860).
set -e

cd /home/user/app

# Build ChromaDB index if it doesn't exist yet (local ONNX embeddings — no API key).
if [ ! -d "data/chroma_db" ] || [ -z "$(ls -A data/chroma_db 2>/dev/null)" ]; then
  echo "[start] Building ChromaDB index from data/raw ..."
  python -m app.ingestion.chunker || echo "[start] WARN: index build failed; will run with whatever exists"
fi

# NOTE: the knowledge graph is read from Neo4j Aura (set NEO4J_* secrets).
# We do NOT rebuild the graph here (it already exists in Aura and matches data/raw).

echo "[start] Launching Chainlit on 0.0.0.0:7860 ..."
exec chainlit run app/chainlit_app.py --host 0.0.0.0 --port 7860 --headless
