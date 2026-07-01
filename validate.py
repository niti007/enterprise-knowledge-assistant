"""
validate.py — Phase 1 validation gate
======================================
Run this after completing Phase 1 setup and data generation.

Usage:
    python validate.py

Checks:
    A. Env vars present
    B. Service connectivity (OpenAI, Langfuse, Neo4j, Redis)
    C. ChromaDB has embeddings
    D. FastAPI /health → 200
    E. FastAPI /chat → answer + citation + trace_id

Exit code 0 = all pass, 1 = failures found.
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

# Colour helpers
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
RESET = "\033[0m"


def ok(msg: str) -> None:
    print(f"  {GREEN}[PASS]{RESET} {msg}")


def fail(msg: str) -> None:
    print(f"  {RED}[FAIL]{RESET} {msg}")


def warn(msg: str) -> None:
    print(f"  {YELLOW}[WARN]{RESET} {msg}")


results: list[tuple[str, bool]] = []


def check(name: str, passed: bool, detail: str = "") -> bool:
    results.append((name, passed))
    (ok if passed else fail)(f"{name}{': ' + detail if detail else ''}")
    return passed


# ---------------------------------------------------------------------------
# A. Environment variables
# ---------------------------------------------------------------------------

def check_env() -> None:
    print("\n[A] Environment Variables")
    required = ["OPENAI_API_KEY"]
    optional = ["LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY", "NEO4J_URI", "TAVILY_API_KEY"]

    for key in required:
        val = os.getenv(key, "")
        check(key, bool(val and not val.startswith("sk-...")), "set" if val else "MISSING")

    for key in optional:
        val = os.getenv(key, "")
        if val:
            ok(f"{key} = set (optional)")
        else:
            warn(f"{key} not set (optional)")


# ---------------------------------------------------------------------------
# B. Service connectivity
# ---------------------------------------------------------------------------

def check_services() -> None:
    print("\n[B] Service Connectivity")

    # OpenAI
    try:
        from openai import OpenAI
        from app.config import get_settings
        s = get_settings()
        client = OpenAI(api_key=s.openai_api_key, base_url=s.openai_base_url)
        client.models.list()
        check("OpenAI API", True, "models.list() OK")
    except Exception as exc:
        check("OpenAI API", False, str(exc)[:80])

    # Langfuse
    try:
        from app.config import get_settings
        s = get_settings()
        if s.langfuse_enabled:
            import httpx
            r = httpx.get(f"{s.langfuse_host}/api/public/health", timeout=5)
            check("Langfuse", r.status_code < 400, f"HTTP {r.status_code}")
        else:
            warn("Langfuse not configured (optional)")
    except Exception as exc:
        check("Langfuse", False, str(exc)[:80])

    # Redis
    try:
        import redis
        from app.config import get_settings
        s = get_settings()
        r = redis.Redis(host=s.redis_host, port=s.redis_port, socket_connect_timeout=3)
        r.ping()
        check("Redis", True, "PONG")
    except Exception as exc:
        warn(f"Redis: {str(exc)[:60]} (optional for Phase 1)")

    # Neo4j
    try:
        from neo4j import GraphDatabase
        from app.config import get_settings
        s = get_settings()
        driver = GraphDatabase.driver(s.neo4j_uri, auth=(s.neo4j_user, s.neo4j_password))
        driver.verify_connectivity()
        driver.close()
        check("Neo4j", True, "bolt OK")
    except Exception as exc:
        warn(f"Neo4j: {str(exc)[:60]} (optional for Phase 1)")


# ---------------------------------------------------------------------------
# C. ChromaDB
# ---------------------------------------------------------------------------

def check_chroma() -> None:
    print("\n[C] ChromaDB Index")
    try:
        import chromadb
        from app.config import get_settings
        s = get_settings()
        client = chromadb.PersistentClient(path=str(s.chroma_persist_path))
        collection = client.get_collection(s.chroma_collection_name)
        count = collection.count()
        check("ChromaDB collection exists", True, f"{count} embeddings")
        check("ChromaDB has embeddings", count > 0, f"{count} > 0")
    except Exception as exc:
        check("ChromaDB", False, str(exc)[:80])
        print("    → Run: python -m app.ingestion.chunker")


# ---------------------------------------------------------------------------
# D & E. FastAPI endpoints
# ---------------------------------------------------------------------------

def check_api() -> None:
    print("\n[D+E] FastAPI Endpoints")
    base = os.getenv("FASTAPI_URL", "http://localhost:8001")

    try:
        import httpx
    except ImportError:
        warn("httpx not installed — skipping API checks")
        return

    # Health
    try:
        r = httpx.get(f"{base}/health", timeout=5)
        check("/health → 200", r.status_code == 200, f"HTTP {r.status_code}")
    except Exception as exc:
        check("/health", False, f"Cannot reach {base}: {exc}")
        print("    → Run: uvicorn app.main:app --port 8001")
        return

    # Chat
    try:
        r = httpx.post(
            f"{base}/chat",
            json={"message": "Who owns the Payment-Service?", "top_k": 3},
            timeout=30,
        )
        check("/chat → 200", r.status_code == 200, f"HTTP {r.status_code}")
        if r.status_code == 200:
            data = r.json()
            has_answer = bool(data.get("answer"))
            has_citation = len(data.get("citations", [])) > 0
            has_trace = bool(data.get("trace_id"))
            check("/chat has answer", has_answer)
            check("/chat has ≥1 citation", has_citation, f"{len(data.get('citations', []))} citations")
            check("/chat has trace_id", has_trace, data.get("trace_id", "MISSING")[:20])
    except Exception as exc:
        check("/chat", False, str(exc)[:80])


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

def main() -> int:
    print("=" * 60)
    print(" Enterprise Knowledge Assistant — Phase 1 Validation")
    print("=" * 60)

    # Load .env
    from dotenv import load_dotenv
    load_dotenv()

    check_env()
    check_services()
    check_chroma()
    check_api()

    print("\n" + "=" * 60)
    print(" SUMMARY")
    print("=" * 60)
    passed = sum(1 for _, p in results if p)
    failed = sum(1 for _, p in results if not p)
    for name, p in results:
        print(f"  {'[PASS]' if p else '[FAIL]'} {name}")
    print(f"\n  Total: {passed} passed, {failed} failed")

    if failed == 0:
        print(f"\n{GREEN}All checks passed — Phase 1 is GREEN.{RESET}")
        return 0
    else:
        print(f"\n{RED}{failed} check(s) failed — fix before proceeding.{RESET}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
