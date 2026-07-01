"""
app/config.py — centralised settings via pydantic-settings.
Reads from .env (or environment). Fails loudly if required vars are missing.
"""
from __future__ import annotations

import os
import sys
from functools import lru_cache
from pathlib import Path

from typing import Optional

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # OpenAI / OpenRouter (chat)
    openai_api_key: str = Field(..., description="OpenAI API key — required")
    openai_base_url: Optional[str] = Field(
        None, description="Override base URL for the OpenAI-compatible client (e.g. OpenRouter). None = default OpenAI."
    )

    # Embeddings
    embedding_provider: str = Field("openai", description="'local' (ChromaDB ONNX MiniLM) or 'openai'")

    # Langfuse
    langfuse_public_key: str = Field("", description="Langfuse public key")
    langfuse_secret_key: str = Field("", description="Langfuse secret key")
    langfuse_host: str = Field("https://cloud.langfuse.com", description="Langfuse host")

    # Neo4j
    neo4j_uri: str = Field("bolt://localhost:7687")
    neo4j_user: str = Field("neo4j")
    neo4j_password: str = Field("password")
    neo4j_database: str = Field("neo4j")

    # Redis
    redis_host: str = Field("localhost")
    redis_port: int = Field(6379)
    redis_password: str = Field("")

    # Optional keys
    tavily_api_key: str = Field("", description="Tavily web search (optional)")
    cohere_api_key: str = Field("", description="Cohere rerank (optional)")

    # App
    app_env: str = Field("development")
    log_level: str = Field("INFO")

    # Models
    llm_default_model: str = Field("gpt-4o-mini")
    llm_advanced_model: str = Field("gpt-4o")
    embedding_model: str = Field("text-embedding-3-small")

    # ChromaDB
    chroma_persist_dir: str = Field("./data/chroma_db")
    chroma_collection_name: str = Field("enterprise_kb")

    # Chunking
    chunk_size: int = Field(500)
    chunk_overlap: int = Field(50)

    # Retrieval
    retrieval_top_k: int = Field(5)

    # Hybrid / rerank
    rerank_model: str = Field("cross-encoder/ms-marco-MiniLM-L-6-v2")
    hybrid_top_n: int = Field(8)

    # Semantic cache
    semantic_cache_threshold: float = Field(0.92)
    semantic_cache_ttl_s: int = Field(3600)
    semantic_cache_enabled: bool = Field(True)

    # Guardrails
    max_input_chars: int = Field(4000)

    @field_validator("openai_api_key")
    @classmethod
    def openai_key_must_be_set(cls, v: str) -> str:
        if not v or v.startswith("sk-..."):
            raise ValueError(
                "\n\n[CONFIG ERROR] OPENAI_API_KEY is not set.\n"
                "  1. Copy .env.example → .env\n"
                "  2. Set OPENAI_API_KEY=sk-<your key>\n"
                "  Get a key at https://platform.openai.com/api-keys\n"
            )
        return v

    @property
    def langfuse_enabled(self) -> bool:
        return bool(self.langfuse_public_key and self.langfuse_secret_key)

    @property
    def chroma_persist_path(self) -> Path:
        p = Path(self.chroma_persist_dir)
        p.mkdir(parents=True, exist_ok=True)
        return p


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Cached settings singleton. Import and call this everywhere."""
    return Settings()
