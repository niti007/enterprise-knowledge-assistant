"""
ingestion/graph_builder.py
===========================
LLM-based entity/relation extraction from data/raw/*.{md,pdf} docs, plus
deterministic node seeding from the CSVs (users, products, transactions).
Writes everything to Neo4j (Aura cloud or local) using MERGE so re-runs are
idempotent.

Node label: `:Entity` with properties {name, type}
  type in {Person, Team, System, Service, Component, SOP, Incident, Product}
Relationship types: DEPENDS_ON, OWNS, RELATED_TO, MANAGES, RESOLVED_BY

Run:
    python -m app.ingestion.graph_builder
"""
from __future__ import annotations

import csv
import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import structlog

from app.config import get_settings
from app.ingestion.loader import RAW_DIR, load_all

log = structlog.get_logger(__name__)
settings = get_settings()

ALLOWED_REL_TYPES = {"DEPENDS_ON", "OWNS", "RELATED_TO", "MANAGES", "RESOLVED_BY"}
ALLOWED_NODE_TYPES = {
    "Person", "Team", "System", "Service", "Component", "SOP", "Incident", "Product",
}

_EXTRACTION_SYSTEM_PROMPT = """\
You are an information-extraction engine for an enterprise knowledge graph.
Given a document, extract entities and relationships mentioned in it.

Entity types allowed: Person, Team, System, Service, Component, SOP, Incident, Product.
Relationship types allowed: DEPENDS_ON, OWNS, RELATED_TO, MANAGES, RESOLVED_BY.

Rules:
- Only extract entities/relations that are explicitly stated or strongly implied by the text.
- Use canonical, consistent names (e.g. "Payment-Service", "Auth-DB", "Priya Sharma", "Billing",
  "SOP-17"). Do not invent new aliases for the same thing.
- DEPENDS_ON: technical dependency (service/system A depends on service/system B).
- OWNS: a team/person owns a service/system/component.
- MANAGES: a person manages a team.
- RESOLVED_BY: an incident was resolved by following a SOP.
- RELATED_TO: any other meaningful relation not covered above.
- Output STRICT JSON only, no markdown fences, no commentary, matching this schema:

{
  "entities": [{"name": "...", "type": "Person|Team|System|Service|Component|SOP|Incident|Product"}],
  "relations": [{"source": "...", "type": "DEPENDS_ON|OWNS|RELATED_TO|MANAGES|RESOLVED_BY", "target": "..."}]
}

If nothing relevant is found, return {"entities": [], "relations": []}.
"""


# ---------------------------------------------------------------------------
# LLM extraction
# ---------------------------------------------------------------------------

def _get_llm_client():
    from openai import OpenAI

    return OpenAI(api_key=settings.openai_api_key, base_url=settings.openai_base_url)


def _extract_json(raw: str) -> dict[str, Any]:
    """Best-effort parse of the LLM's JSON output (strip code fences if present)."""
    text = raw.strip()
    text = re.sub(r"^```(json)?", "", text).strip()
    text = re.sub(r"```$", "", text).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                pass
        log.warning("graph_extraction_parse_failed", raw_preview=text[:200])
        return {"entities": [], "relations": []}


def extract_entities_relations(doc_text: str, source: str, client=None) -> dict[str, Any]:
    """Call the LLM (via OpenRouter) to extract entities + relations from one doc."""
    client = client or _get_llm_client()
    # Truncate very long docs to keep prompt small/cheap.
    snippet = doc_text[:6000]

    completion = client.chat.completions.create(
        model=settings.llm_default_model,
        messages=[
            {"role": "system", "content": _EXTRACTION_SYSTEM_PROMPT},
            {"role": "user", "content": f"Document source: {source}\n\n{snippet}"},
        ],
        temperature=0.0,
        max_tokens=1500,
    )
    raw = completion.choices[0].message.content or "{}"
    data = _extract_json(raw)

    entities = [
        e for e in data.get("entities", [])
        if isinstance(e, dict) and e.get("name") and e.get("type") in ALLOWED_NODE_TYPES
    ]
    relations = [
        r for r in data.get("relations", [])
        if isinstance(r, dict)
        and r.get("source") and r.get("target") and r.get("type") in ALLOWED_REL_TYPES
    ]
    return {"entities": entities, "relations": relations, "source": source}


# ---------------------------------------------------------------------------
# CSV seeding (deterministic, no LLM needed)
# ---------------------------------------------------------------------------

def seed_from_csvs(raw_dir: Path) -> dict[str, Any]:
    """Build deterministic entities/relations from users.csv / products.csv."""
    entities: list[dict[str, str]] = []
    relations: list[dict[str, str]] = []
    seen_entities: set[tuple[str, str]] = set()
    seen_rel: set[tuple[str, str, str]] = set()

    def add_entity(name: str, etype: str) -> None:
        key = (name, etype)
        if key not in seen_entities:
            seen_entities.add(key)
            entities.append({"name": name, "type": etype})

    def add_rel(src: str, rtype: str, tgt: str) -> None:
        key = (src, rtype, tgt)
        if key not in seen_rel:
            seen_rel.add(key)
            relations.append({"source": src, "type": rtype, "target": tgt})

    users_csv = raw_dir / "users.csv"
    if users_csv.exists():
        with users_csv.open(encoding="utf-8", newline="") as f:
            for row in csv.DictReader(f):
                name = row.get("name", "").strip()
                team = row.get("team", "").strip()
                role = (row.get("role") or "").strip().lower()
                if not name:
                    continue
                add_entity(name, "Person")
                if team:
                    add_entity(team, "Team")
                    if "lead" in role or "manager" in role:
                        add_rel(name, "MANAGES", team)
                    else:
                        add_rel(name, "RELATED_TO", team)

    products_csv = raw_dir / "products.csv"
    if products_csv.exists():
        with products_csv.open(encoding="utf-8", newline="") as f:
            for row in csv.DictReader(f):
                name = (row.get("name") or "").strip()
                owner_team = (row.get("owner_team") or "").strip()
                if not name:
                    continue
                add_entity(name, "Product")
                if owner_team:
                    add_entity(owner_team, "Team")
                    add_rel(owner_team, "OWNS", name)

    return {"entities": entities, "relations": relations, "source": "csv_seed"}


# ---------------------------------------------------------------------------
# Neo4j writer
# ---------------------------------------------------------------------------

class GraphWriter:
    """Idempotent Neo4j writer using MERGE for nodes/relationships."""

    def __init__(self) -> None:
        from neo4j import GraphDatabase

        self._driver = GraphDatabase.driver(
            settings.neo4j_uri, auth=(settings.neo4j_user, settings.neo4j_password)
        )
        self._database = settings.neo4j_database

    def close(self) -> None:
        self._driver.close()

    def verify(self) -> None:
        with self._driver.session(database=self._database) as session:
            session.run("RETURN 1").consume()

    def clear_all(self) -> None:
        """Wipe all Entity nodes/relationships (idempotent full rebuild)."""
        with self._driver.session(database=self._database) as session:
            session.run("MATCH (n:Entity) DETACH DELETE n")

    def merge_entity(self, session, name: str, etype: str, source: str) -> None:
        session.run(
            """
            MERGE (n:Entity {name: $name})
            ON CREATE SET n.type = $type, n.sources = [$source]
            ON MATCH SET n.type = coalesce(n.type, $type),
                         n.sources = CASE WHEN $source IN n.sources THEN n.sources
                                          ELSE n.sources + $source END
            """,
            name=name, type=etype, source=source,
        )

    def merge_relation(self, session, src: str, rtype: str, tgt: str, source: str) -> None:
        # rtype is constrained to ALLOWED_REL_TYPES (validated upstream) so this is safe
        # to interpolate into the Cypher relationship-type position.
        query = f"""
            MATCH (a:Entity {{name: $src}})
            MATCH (b:Entity {{name: $tgt}})
            MERGE (a)-[r:{rtype}]->(b)
            ON CREATE SET r.sources = [$source]
            ON MATCH SET r.sources = CASE WHEN $source IN r.sources THEN r.sources
                                          ELSE r.sources + $source END
            """
        session.run(query, src=src, tgt=tgt, source=source)

    def write_batch(self, entities: list[dict[str, str]], relations: list[dict[str, str]], source: str) -> None:
        with self._driver.session(database=self._database) as session:
            known_names = {e["name"] for e in entities}
            for e in entities:
                self.merge_entity(session, e["name"], e["type"], source)
            # Ensure relation endpoints exist even if not explicitly in the entities list,
            # defaulting to a generic "Component" type (won't overwrite an existing type
            # thanks to ON MATCH SET n.type = coalesce(n.type, $type) in merge_entity).
            for r in relations:
                if r["type"] not in ALLOWED_REL_TYPES:
                    continue
                if r["source"] not in known_names:
                    self.merge_entity(session, r["source"], "Component", source)
                if r["target"] not in known_names:
                    self.merge_entity(session, r["target"], "Component", source)
            for r in relations:
                if r["type"] not in ALLOWED_REL_TYPES:
                    continue
                try:
                    self.merge_relation(session, r["source"], r["type"], r["target"], source)
                except Exception as exc:
                    log.warning("relation_write_failed", rel=r, error=str(exc))

    def counts(self) -> dict[str, int]:
        with self._driver.session(database=self._database) as session:
            node_count = session.run("MATCH (n:Entity) RETURN count(n) AS c").single()["c"]
            edge_count = session.run("MATCH (:Entity)-[r]->(:Entity) RETURN count(r) AS c").single()["c"]
        return {"nodes": node_count, "edges": edge_count}


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

def build_graph(raw_dir: Path | None = None, clear_first: bool = True) -> dict[str, int]:
    directory = raw_dir or RAW_DIR
    writer = GraphWriter()
    try:
        writer.verify()
        log.info("neo4j_connected", uri=settings.neo4j_uri, database=settings.neo4j_database)

        if clear_first:
            print("[graph_builder] Clearing existing :Entity graph (idempotent rebuild) …")
            writer.clear_all()

        # 1. Deterministic CSV seeding first (cheap, no LLM)
        print("[graph_builder] Seeding entities from CSVs …")
        csv_batch = seed_from_csvs(directory)
        writer.write_batch(csv_batch["entities"], csv_batch["relations"], csv_batch["source"])
        print(
            f"[graph_builder]   CSV seed: {len(csv_batch['entities'])} entities, "
            f"{len(csv_batch['relations'])} relations"
        )

        # 2. LLM extraction over text docs (md/pdf), skip raw CSVs (already seeded)
        docs = [d for d in load_all(directory) if d["metadata"]["doc_type"] != "csv"]
        client = _get_llm_client()

        print(f"[graph_builder] Extracting entities/relations from {len(docs)} documents via LLM …")
        for i, doc in enumerate(docs, 1):
            source = doc["metadata"]["source"]
            try:
                result = extract_entities_relations(doc["text"], source, client=client)
            except Exception as exc:
                log.warning("llm_extraction_failed", source=source, error=str(exc))
                continue
            writer.write_batch(result["entities"], result["relations"], source)
            print(
                f"[graph_builder]   ({i}/{len(docs)}) {source}: "
                f"{len(result['entities'])} entities, {len(result['relations'])} relations"
            )

        counts = writer.counts()
        print(f"[graph_builder] DONE. Neo4j now has {counts['nodes']} nodes, {counts['edges']} edges.")
        return counts
    finally:
        writer.close()


if __name__ == "__main__":
    build_graph()
