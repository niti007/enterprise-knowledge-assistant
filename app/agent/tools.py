"""
agent/tools.py
================
LangChain tools used by the LangGraph agent:
    - retrieve    : hybrid retrieval (vector + graph + rerank) — primary tool
    - web_search  : Tavily web search (degrades to disabled if no API key)
    - sql_query   : read-only SQL over an in-memory SQLite built from the CSVs
    - python_exec : sandboxed Python for calculations (no file/network/os/sys/subprocess)

All tools are safe to call even if optional dependencies/keys are missing —
they return a descriptive string rather than raising.
"""
from __future__ import annotations

import csv
import io
import sqlite3
import sys
from contextlib import redirect_stdout
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import structlog
from langchain_core.tools import tool

from app.config import get_settings

log = structlog.get_logger(__name__)
settings = get_settings()

RAW_DIR = ROOT / "data" / "raw"


# ---------------------------------------------------------------------------
# retrieve — hybrid retrieval
# ---------------------------------------------------------------------------

@tool("retrieve", return_direct=False)
def retrieve_tool(query: str) -> str:
    """Search the company knowledge base (policies, SOPs, manuals, incident
    reports) AND the knowledge graph (entity relationships like DEPENDS_ON,
    OWNS, MANAGES, RESOLVED_BY) for information relevant to `query`. Use this
    FIRST for any question about internal systems, teams, people, policies,
    or incidents. Returns the top matching passages with their sources."""
    from app.retrieval.hybrid import hybrid_search

    try:
        results = hybrid_search(query)
    except Exception as exc:
        return f"[retrieve error] {exc}"

    if not results:
        return "No relevant documents or graph facts found."

    lines = []
    for r in results:
        meta = r.get("metadata", {})
        src = meta.get("source", r.get("source", "unknown"))
        lines.append(f"[{src}] {r['text']}")
    return "\n\n".join(lines)


# ---------------------------------------------------------------------------
# web_search — Tavily (graceful degrade if no key)
# ---------------------------------------------------------------------------

@tool("web_search", return_direct=False)
def web_search_tool(query: str) -> str:
    """Search the public web for information NOT found in the internal
    knowledge base (e.g. general facts, current events, external docs). Only
    use this if `retrieve` did not return enough relevant information."""
    if not settings.tavily_api_key:
        return (
            "[web_search unavailable] No TAVILY_API_KEY configured — "
            "web search is disabled. Answer using internal knowledge base results only."
        )
    try:
        from tavily import TavilyClient

        client = TavilyClient(api_key=settings.tavily_api_key)
        resp = client.search(query=query, max_results=5)
        results = resp.get("results", [])
        if not results:
            return "No web results found."
        lines = []
        for r in results:
            lines.append(f"[{r.get('url', 'web')}] {r.get('title', '')}\n{r.get('content', '')[:500]}")
        return "\n\n".join(lines)
    except Exception as exc:
        log.warning("web_search_failed", error=str(exc))
        return f"[web_search error] {exc}"


# ---------------------------------------------------------------------------
# sql_query — read-only SQLite over the CSVs
# ---------------------------------------------------------------------------

_WRITE_KEYWORDS = (
    "insert", "update", "delete", "drop", "alter", "create", "replace",
    "attach", "detach", "pragma", "vacuum", "reindex",
)


def _build_sqlite_db() -> sqlite3.Connection:
    """Load all CSVs in data/raw/ into an in-memory SQLite DB. Table name =
    CSV filename stem (e.g. users.csv -> table 'users')."""
    conn = sqlite3.connect(":memory:")
    if not RAW_DIR.exists():
        return conn

    for csv_path in sorted(RAW_DIR.glob("*.csv")):
        table = csv_path.stem.replace("-", "_")
        with csv_path.open(encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            try:
                header = next(reader)
            except StopIteration:
                continue
            cols = ", ".join(f'"{c}" TEXT' for c in header)
            conn.execute(f'CREATE TABLE "{table}" ({cols})')
            placeholders = ", ".join("?" for _ in header)
            rows = list(reader)
            if rows:
                conn.executemany(f'INSERT INTO "{table}" VALUES ({placeholders})', rows)
    conn.commit()
    return conn


_sql_conn: sqlite3.Connection | None = None


def _get_sql_conn() -> sqlite3.Connection:
    global _sql_conn
    if _sql_conn is None:
        _sql_conn = _build_sqlite_db()
    return _sql_conn


@tool("sql_query", return_direct=False)
def sql_query_tool(query: str) -> str:
    """Run a READ-ONLY SQL SELECT query against the structured company data
    (tables: users, products, transactions, doc_metadata — loaded from CSVs).
    Use this for aggregate/structured questions like counts, sums, filters,
    joins. Only SELECT statements are allowed; writes are blocked."""
    q_stripped = query.strip().rstrip(";")
    q_lower = q_stripped.lower()

    if not q_lower.startswith("select"):
        return "[sql_query blocked] Only SELECT statements are allowed."
    if any(kw in q_lower for kw in _WRITE_KEYWORDS):
        return "[sql_query blocked] Query contains a disallowed write/DDL keyword."
    if ";" in q_stripped:
        return "[sql_query blocked] Multiple statements are not allowed."

    try:
        conn = _get_sql_conn()
        cur = conn.execute(q_stripped)
        cols = [d[0] for d in cur.description] if cur.description else []
        rows = cur.fetchmany(200)
        if not rows:
            return "Query returned 0 rows."
        lines = [", ".join(cols)]
        for row in rows:
            lines.append(", ".join(str(v) for v in row))
        return "\n".join(lines)
    except Exception as exc:
        return f"[sql_query error] {exc}"


# ---------------------------------------------------------------------------
# python_exec — sandboxed calculation tool
# ---------------------------------------------------------------------------

import builtins as _builtins_module

_SAFE_BUILTIN_NAMES = (
    "abs", "all", "any", "bool", "dict", "enumerate", "float", "int", "len",
    "list", "max", "min", "pow", "range", "round", "set", "sorted", "str",
    "sum", "tuple", "zip", "print",
)
_SAFE_BUILTINS = {
    name: getattr(_builtins_module, name)
    for name in _SAFE_BUILTIN_NAMES
    if hasattr(_builtins_module, name)
}

_BLOCKED_TOKENS = (
    "import", "open(", "exec(", "eval(", "__", "os.", "sys.", "subprocess",
    "socket", "requests", "input(", "compile(", "globals(", "locals(",
)


@tool("python_exec", return_direct=False)
def python_exec_tool(code: str) -> str:
    """Execute a short, sandboxed Python snippet for calculations (math,
    aggregations over numbers you already have). No file, network, or OS
    access; no imports. Print the result with print(). Times out after a few
    seconds of CPU work is not enforced precisely — keep code trivial."""
    lowered = code.lower()
    if any(tok in lowered for tok in _BLOCKED_TOKENS):
        return "[python_exec blocked] Code contains a disallowed token (import/file/network/os access)."
    if len(code) > 2000:
        return "[python_exec blocked] Code too long."

    safe_globals: dict[str, Any] = {"__builtins__": _SAFE_BUILTINS}
    buf = io.StringIO()
    try:
        with redirect_stdout(buf):
            exec(code, safe_globals, {})
        output = buf.getvalue().strip()
        return output if output else "[python_exec] Code ran with no printed output."
    except Exception as exc:
        return f"[python_exec error] {type(exc).__name__}: {exc}"


# ---------------------------------------------------------------------------
# Tool registry
# ---------------------------------------------------------------------------

def get_tools() -> list:
    """Return the list of LangChain tools available to the agent."""
    return [retrieve_tool, web_search_tool, sql_query_tool, python_exec_tool]
