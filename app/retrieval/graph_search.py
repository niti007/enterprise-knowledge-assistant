"""
retrieval/graph_search.py
==========================
Neo4j Cypher traversal for graph-based retrieval.

Given a free-text query, pull out candidate entity names (simple keyword /
capitalized-token matching against known node names — cheap and good enough
for this corpus's controlled vocabulary), then traverse 1-2 hops out from any
matching nodes and render the resulting paths as short text snippets tagged
with source='graph', so they can be merged with vector chunks in hybrid.py.

Usage:
    from app.retrieval.graph_search import GraphSearcher
    gs = GraphSearcher()
    results = gs.search("If Payment-Service goes down, who do I contact?", k=8)
    # -> [{"text": "...", "source": "graph", "score": 0.8, "metadata": {...}}, ...]
"""
from __future__ import annotations

import re
import sys
from functools import lru_cache
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import structlog

from app.config import get_settings

log = structlog.get_logger(__name__)
settings = get_settings()

_REL_VERB = {
    "DEPENDS_ON": "depends on",
    "OWNS": "owns",
    "RELATED_TO": "is related to",
    "MANAGES": "manages",
    "RESOLVED_BY": "was resolved by",
}


class GraphSearcher:
    """Lazily-connected Neo4j searcher. Degrades to empty results if Neo4j
    is unreachable, so the hybrid retriever never crashes on a graph outage."""

    def __init__(self) -> None:
        self._driver = None
        self._available: bool | None = None
        self._node_names_cache: list[str] | None = None

    # ------------------------------------------------------------------
    def _get_driver(self):
        if self._driver is None:
            from neo4j import GraphDatabase

            self._driver = GraphDatabase.driver(
                settings.neo4j_uri, auth=(settings.neo4j_user, settings.neo4j_password)
            )
        return self._driver

    def is_available(self) -> bool:
        if self._available is not None:
            return self._available
        try:
            driver = self._get_driver()
            with driver.session(database=settings.neo4j_database) as session:
                session.run("RETURN 1").consume()
            self._available = True
        except Exception as exc:
            log.warning("graph_search_unavailable", error=str(exc))
            self._available = False
        return self._available

    # ------------------------------------------------------------------
    def _all_node_names(self) -> list[str]:
        if self._node_names_cache is not None:
            return self._node_names_cache
        if not self.is_available():
            self._node_names_cache = []
            return []
        driver = self._get_driver()
        with driver.session(database=settings.neo4j_database) as session:
            result = session.run("MATCH (n:Entity) RETURN n.name AS name")
            names = [r["name"] for r in result if r["name"]]
        self._node_names_cache = names
        return names

    def _match_entities(self, query: str) -> list[str]:
        """Find known graph node names mentioned in the query (case-insensitive
        substring match against the node name; also tries hyphen/space variants)."""
        names = self._all_node_names()
        if not names:
            return []
        q_lower = query.lower()
        matched: list[str] = []
        for name in names:
            n_lower = name.lower()
            variants = {n_lower, n_lower.replace("-", " "), n_lower.replace(" ", "-")}
            if any(v in q_lower for v in variants if v):
                matched.append(name)
        # Fallback: capitalized-token heuristic (e.g. "Payment-Service", "Auth-DB")
        if not matched:
            tokens = re.findall(r"[A-Z][A-Za-z0-9_-]{2,}", query)
            for tok in tokens:
                for name in names:
                    if tok.lower() in name.lower() or name.lower() in tok.lower():
                        matched.append(name)
        return list(dict.fromkeys(matched))  # dedup, keep order

    # ------------------------------------------------------------------
    def search(self, query: str, k: int | None = None, hops: int = 2) -> list[dict[str, Any]]:
        """Traverse the graph for entities mentioned in `query`, return text
        snippets describing related facts/paths, tagged source='graph'."""
        top_k = k or settings.retrieval_top_k
        if not self.is_available():
            return []

        seeds = self._match_entities(query)
        if not seeds:
            return []

        driver = self._get_driver()
        snippets: list[dict[str, Any]] = []
        seen: set[str] = set()

        with driver.session(database=settings.neo4j_database) as session:
            for seed in seeds:
                cypher = """
                    MATCH path = (a:Entity {name: $seed})-[r*1..%d]-(b:Entity)
                    RETURN path
                    LIMIT 25
                """ % max(1, min(hops, 3))
                try:
                    result = session.run(cypher, seed=seed)
                    for record in result:
                        path = record["path"]
                        for rel in path.relationships:
                            start_name = rel.start_node["name"]
                            end_name = rel.end_node["name"]
                            verb = _REL_VERB.get(rel.type, rel.type.lower().replace("_", " "))
                            fact = f"{start_name} {verb} {end_name}."
                            if fact in seen:
                                continue
                            seen.add(fact)
                            snippets.append({
                                "text": fact,
                                "source": "graph",
                                "metadata": {
                                    "source": "graph",
                                    "doc_type": "graph_fact",
                                    "dept": "",
                                    "relation": rel.type,
                                    "from": start_name,
                                    "to": end_name,
                                },
                                "score": 0.75,
                            })
                except Exception as exc:
                    log.warning("graph_traversal_failed", seed=seed, error=str(exc))

        # Rank shorter/more direct facts first (proxy: keep order), cap to top_k
        for i, s in enumerate(snippets[:top_k]):
            s["rank"] = i + 1
        return snippets[:top_k]

    def close(self) -> None:
        if self._driver is not None:
            self._driver.close()
            self._driver = None


@lru_cache(maxsize=1)
def get_graph_searcher() -> GraphSearcher:
    return GraphSearcher()
