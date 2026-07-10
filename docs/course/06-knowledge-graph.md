# Chapter 6 — The Knowledge Graph (`graph_builder.py` and `graph_search.py`)

## Why this / what's the need

Imagine you ask a coworker: "If Payment-Service goes down, who do I call?"

A plain document search can find a paragraph that *mentions* "Payment-Service." But it
can't easily tell you "Payment-Service depends on Auth-DB, and Auth-DB is owned by the
Platform Team, and the Platform Team is managed by Priya Sharma." That's a chain of
*connections* between things — not a fact sitting in one paragraph.

That's exactly what a company org chart or a family tree gives you: not just "who is
this person," but "who reports to whom," "who is married to whom," "who owns what."
A **graph database** is the computer version of that org chart/family tree, and it's
what this project uses to answer multi-step "who/what is connected to what" questions
that plain text search is bad at.

> 🔑 **New word — graph database:** a database that stores information as a bunch of
> "things" and the "connections" between them (like a family tree or org chart), instead
> of rows in a table.

> 🔑 **New word — node:** one "thing" in the graph — a person, a team, a system, a
> product, etc. In this project every node has the label `:Entity`.

> 🔑 **New word — edge (relationship):** a labeled arrow connecting two nodes, saying
> *how* they're connected — e.g. "Priya Sharma `MANAGES` Platform Team."

> 🔑 **New word — Cypher:** the query language for Neo4j (the graph database this
> project uses), similar in spirit to SQL but built around "find this node, then follow
> its arrows."

> 🔑 **New word — traversal:** the act of walking from one node, across its edges, to
> nearby nodes — like tracing a finger across an org chart from a name to their boss's
> boss.

> 🔑 **New word — hop:** one step across a single edge during a traversal. "2 hops"
> means "follow two arrows away from the starting node."

This project uses [Neo4j](https://neo4j.com/) (a popular graph database, running in the
cloud on "Neo4j Aura") as that org-chart/family-tree store. Two files handle it:
- `app/ingestion/graph_builder.py` — **builds** the graph (reads documents + CSVs, writes
  nodes and edges into Neo4j).
- `app/retrieval/graph_search.py` — **queries** the graph at question time (finds nodes
  mentioned in a user's question, walks a couple of hops, turns what it finds into plain
  sentences).

---

## Part 1: Building the graph — `app/ingestion/graph_builder.py`

### The vocabulary this project's graph uses

Before any code, know the fixed vocabulary the whole graph is built from (defined at the
top of the file):

```python
ALLOWED_REL_TYPES = {"DEPENDS_ON", "OWNS", "RELATED_TO", "MANAGES", "RESOLVED_BY"}
ALLOWED_NODE_TYPES = {
    "Person", "Team", "System", "Service", "Component", "SOP", "Incident", "Product",
}
```

- `ALLOWED_NODE_TYPES` — every node (every "box" in the org chart) must be one of these
  8 kinds of thing: a Person, a Team, a System, a Service, a Component, an SOP
  (standard operating procedure document), an Incident, or a Product.
- `ALLOWED_REL_TYPES` — every edge (every "arrow") must be one of these 5 relationship
  types: `DEPENDS_ON` (a system needs another system to work), `OWNS` (a team/person is
  responsible for something), `MANAGES` (a person manages a team), `RESOLVED_BY` (an
  incident was fixed by following an SOP), or `RELATED_TO` (a catch-all for anything
  else meaningful).

Keeping this list small and fixed is deliberate — it stops the graph from growing a
messy, inconsistent pile of ad-hoc relationship names.

### Step A — Ask the LLM to read a document and extract the graph facts

```python
def extract_entities_relations(doc_text: str, source: str, client=None) -> dict[str, Any]:
    client = client or _get_llm_client()
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
```

- `snippet = doc_text[:6000]` — only sends the first 6000 characters of a document to
  the LLM, to keep the request small and cheap.
- `client.chat.completions.create(...)` — calls the LLM (through OpenRouter) with a
  system prompt (`_EXTRACTION_SYSTEM_PROMPT`, shown below) telling it exactly what JSON
  shape to return.
- `temperature=0.0` — asks the LLM to be as deterministic/non-random as possible, since
  this is a structured-extraction task, not creative writing.
- `data = _extract_json(raw)` — the LLM's reply is text; this helper strips markdown
  code fences and parses it as JSON (with a regex fallback if the LLM added extra
  commentary around the JSON).
- The two list-comprehensions **filter out anything that isn't in the allowed
  vocabulary** — if the LLM invents a relationship type like `INTEGRATES_WITH`, it's
  silently dropped. This keeps garbage out of the graph even if the LLM misbehaves.

The system prompt that steers this extraction is worth reading in plain English — it
tells the LLM: "Only extract things explicitly stated in the text. Use consistent
canonical names (e.g. always `Payment-Service`, never `payment svc`). Output strict JSON,
no markdown, matching this exact schema." This kind of tight, example-filled prompt is
what makes LLM-based extraction reliable enough to feed into a database.

### Step B — Seed extra nodes deterministically from the CSVs (no LLM needed)

```python
def seed_from_csvs(raw_dir: Path) -> dict[str, Any]:
    ...
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
```

- This function doesn't call the LLM at all — it reads `data/raw/users.csv` and
  `data/raw/products.csv` directly and turns each row into nodes/edges with plain
  Python logic.
- Every person in `users.csv` becomes a `Person` node; their team becomes a `Team` node.
- `if "lead" in role or "manager" in role` — if the CSV says the person's role contains
  "lead" or "manager", the edge is `MANAGES`; otherwise it's the weaker `RELATED_TO`.
- This is "free" graph data — cheap, instant, and 100% accurate (it's just re-shaping
  structured CSV rows), unlike the LLM extraction which is reading unstructured text and
  can occasionally miss or misread something.

### Step C — Write to Neo4j idempotently with `MERGE`

```python
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
```

> 🔑 **New word — MERGE:** a Cypher command meaning "find a node/edge matching this
> pattern; if it already exists, just update it — if it doesn't exist yet, create it."
> This is why re-running the builder doesn't create duplicate nodes.

- `MERGE (n:Entity {name: $name})` — look for an existing node labeled `Entity` with
  this exact `name`. This is the Cypher equivalent of a family tree saying "do we
  already have a box for 'Priya Sharma'? If so, reuse it."
- `ON CREATE SET ...` — runs *only* the first time this node is created (sets its type
  and starts its list of source documents).
- `ON MATCH SET ...` — runs every time the node *already existed* (keeps the original
  type via `coalesce`, and appends this new source document to the list if it isn't
  already there).
- Because of `MERGE`, running `graph_builder.py` five times in a row does **not**
  produce five copies of "Priya Sharma" — it's idempotent (safe to re-run).

```python
def merge_relation(self, session, src: str, rtype: str, tgt: str, source: str) -> None:
    query = f"""
        MATCH (a:Entity {{name: $src}})
        MATCH (b:Entity {{name: $tgt}})
        MERGE (a)-[r:{rtype}]->(b)
        ON CREATE SET r.sources = [$source]
        ON MATCH SET r.sources = CASE WHEN $source IN r.sources THEN r.sources
                                      ELSE r.sources + $source END
        """
    session.run(query, src=src, tgt=tgt, source=source)
```

- `MATCH (a:Entity {name: $src})` / `MATCH (b:Entity {name: $tgt})` — first find the two
  existing nodes (the endpoints of the arrow) by name.
- `MERGE (a)-[r:{rtype}]->(b)` — create the labeled arrow between them (or reuse it if
  it's already there). Note `rtype` is inserted directly into the query text rather than
  as a `$parameter` — Cypher doesn't allow relationship *types* to be parameters, only
  values. This is safe here specifically because `rtype` was already checked against
  `ALLOWED_REL_TYPES` before this function is ever called — it's never raw, un-checked
  user text.

### Step D — Orchestration: `build_graph()`

```python
def build_graph(raw_dir: Path | None = None, clear_first: bool = True) -> dict[str, int]:
    directory = raw_dir or RAW_DIR
    writer = GraphWriter()
    try:
        writer.verify()
        if clear_first:
            writer.clear_all()
        csv_batch = seed_from_csvs(directory)
        writer.write_batch(csv_batch["entities"], csv_batch["relations"], csv_batch["source"])
        docs = [d for d in load_all(directory) if d["metadata"]["doc_type"] != "csv"]
        client = _get_llm_client()
        for i, doc in enumerate(docs, 1):
            result = extract_entities_relations(doc["text"], doc["metadata"]["source"], client=client)
            writer.write_batch(result["entities"], result["relations"], doc["metadata"]["source"])
        counts = writer.counts()
        return counts
    finally:
        writer.close()
```

- `writer.verify()` — makes one throwaway query (`RETURN 1`) just to confirm the Neo4j
  connection actually works before doing real work.
- `writer.clear_all()` — wipes the whole `:Entity` graph first (`clear_first=True` by
  default), so each run is a clean, full rebuild rather than an accumulating mess.
- CSVs are seeded **first** (cheap, instant, no LLM cost), then documents are processed
  **one at a time** through the LLM — this order means the cheap/reliable data lands
  first, and LLM extraction fills in the rest.
- `finally: writer.close()` — always closes the Neo4j connection, even if something
  above raised an exception.

---

## Part 2: Querying the graph — `app/retrieval/graph_search.py`

### Step A — Find which known entities are mentioned in the user's question

```python
def _match_entities(self, query: str) -> list[str]:
    names = self._all_node_names()
    q_lower = query.lower()
    matched: list[str] = []
    for name in names:
        n_lower = name.lower()
        variants = {n_lower, n_lower.replace("-", " "), n_lower.replace(" ", "-")}
        if any(v in q_lower for v in variants if v):
            matched.append(name)
    ...
    return list(dict.fromkeys(matched))
```

- `self._all_node_names()` — pulls every node's `name` out of Neo4j once and caches it
  (there's no fancy NLP here — just a list of every name already in the graph).
- For each known name, it checks three spelling variants (as-is, hyphens turned to
  spaces, spaces turned to hyphens) against the lower-cased question text — so
  "Payment Service" in a question still matches the node named "Payment-Service".
- `list(dict.fromkeys(matched))` — a common Python trick to remove duplicates from a
  list while keeping the original order (a `set()` would lose the order).

### Step B — Traverse 1–2 hops out from each matched entity

```python
cypher = """
    MATCH path = (a:Entity {name: $seed})-[r*1..%d]-(b:Entity)
    RETURN path
    LIMIT 25
""" % max(1, min(hops, 3))
result = session.run(cypher, seed=seed)
```

- `MATCH path = (a:Entity {name: $seed})-[r*1..2]-(b:Entity)` — this is the core Cypher
  traversal. In plain words: "Start at the node named `$seed`. Follow relationships
  (arrows, in either direction) for 1 to 2 hops, and give me every node `b` you land on,
  plus the full path taken to get there."
- `-[r*1..2]-` — the `*1..2` means "between 1 and 2 hops"; this is the actual "walk the
  org chart a couple of steps" behavior described in the intro analogy.
- `LIMIT 25` — caps how many paths come back per seed entity, so one very
  well-connected node can't flood the results.

### Step C — Turn each relationship into a plain English sentence

```python
_REL_VERB = {
    "DEPENDS_ON": "depends on",
    "OWNS": "owns",
    "RELATED_TO": "is related to",
    "MANAGES": "manages",
    "RESOLVED_BY": "was resolved by",
}
...
for rel in path.relationships:
    start_name = rel.start_node["name"]
    end_name = rel.end_node["name"]
    verb = _REL_VERB.get(rel.type, rel.type.lower().replace("_", " "))
    fact = f"{start_name} {verb} {end_name}."
```

- Instead of returning raw graph data (nodes, IDs, relationship codes) to the rest of
  the app, this turns each edge into a readable sentence, e.g. `"Payment-Service depends
  on Auth-DB."` — something an LLM (or a human) can read directly.
- Each fact is packaged as `{"text": fact, "source": "graph", "score": 0.75, ...}` — the
  same shape vector search results use, which is exactly what lets `hybrid.py` (next
  chapter) merge the two kinds of results together without special-casing either one.

### Degrading gracefully

```python
def is_available(self) -> bool:
    if self._available is not None:
        return self._available
    try:
        ...
        self._available = True
    except Exception as exc:
        log.warning("graph_search_unavailable", error=str(exc))
        self._available = False
    return self._available
```

If Neo4j is down or unreachable, `search()` just returns an empty list instead of
crashing the whole app — the assistant falls back to vector search alone. This
"degrade, don't crash" pattern shows up throughout the project.

## ✅ You just learned
- What a **graph database** is (nodes + labeled edges, like an org chart/family tree)
  and why it answers "who's connected to what" questions that plain text search can't.
- Neo4j's **Cypher** query language basics: `MATCH`, `MERGE`, and the `-[r*1..2]-`
  traversal syntax for hopping across relationships.
- How `graph_builder.py` fills the graph two ways: cheap deterministic CSV seeding, and
  LLM-based extraction from documents, both funneled through a fixed, validated
  vocabulary of node types and relationship types.
- Why `MERGE` makes writing to the graph **idempotent** (safe to re-run without
  duplicating data).
- How `graph_search.py` finds entities mentioned in a question, walks 1–2 hops, and
  turns raw graph edges into plain-English sentences tagged `source="graph"`.

## ▶️ Run this now
Build (or rebuild) the graph from the documents and CSVs in `data/raw/`:
```
.venv\Scripts\python.exe -m app.ingestion.graph_builder
```
`graph_search.py` has nothing to run standalone — it's a library used by `hybrid.py`
(the next chapter) and by the `retrieve` agent tool. You can still try it directly in a
Python shell:
```
.venv\Scripts\python.exe -c "from app.retrieval.graph_search import GraphSearcher; print(GraphSearcher().search('Who owns Payment-Service?'))"
```

## 🧠 Check yourself
1. Why does `merge_relation` insert the relationship type (`rtype`) directly into the
   Cypher query text instead of passing it as a `$parameter` like the other values — and
   why is that safe here?
2. What would happen to the graph if you ran `graph_builder.py` three times in a row,
   and why doesn't `MERGE` cause duplicate "Priya Sharma" nodes?
3. If Neo4j were temporarily unreachable, what does `graph_search.py` return, and why is
   that behavior important for the rest of the app?

Continue to the next chapter → 07-hybrid-retrieval.md
