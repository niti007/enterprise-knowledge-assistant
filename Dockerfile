# Hugging Face Space (Docker SDK) — Chainlit UI for the Enterprise Knowledge Assistant.
# The Chainlit app runs the full pipeline in-process (no separate FastAPI needed).
# ChromaDB is rebuilt at startup from the baked-in corpus (local embeddings, free);
# the knowledge graph is read from Neo4j Aura (cloud) via secrets.

FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONIOENCODING=utf-8 \
    HF_HOME=/home/user/.cache/huggingface \
    TRANSFORMERS_CACHE=/home/user/.cache/huggingface \
    CHROMA_PERSIST_DIR=/home/user/app/data/chroma_db

# System deps (build tools for some wheels)
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential curl \
    && rm -rf /var/lib/apt/lists/*

# Non-root user (HF Spaces requirement)
RUN useradd -m -u 1000 user
USER user
ENV PATH="/home/user/.local/bin:$PATH"
WORKDIR /home/user/app

# Install CPU-only torch first (much smaller than the default CUDA build)
RUN pip install --no-cache-dir --user torch --index-url https://download.pytorch.org/whl/cpu

# Python deps (frozen from the working env — guaranteed installable, torch excluded above)
COPY --chown=user requirements-deploy.txt ./
RUN pip install --no-cache-dir --user -r requirements-deploy.txt \
    && python -m spacy download en_core_web_sm

# App code + the exact corpus the Aura graph was built from
COPY --chown=user app ./app
COPY --chown=user data/raw ./data/raw
COPY --chown=user chainlit.md ./chainlit.md
COPY --chown=user start.sh ./start.sh

# Pre-download the CrossEncoder reranker + ONNX embedder into the image cache so
# the first user request isn't a huge cold download.
RUN python -c "from sentence_transformers import CrossEncoder; CrossEncoder('cross-encoder/ms-marco-MiniLM-L-6-v2')" || true

EXPOSE 7860
CMD ["bash", "start.sh"]
