# Chapter 7 — Hybrid Retrieval and Re-Ranking (`app/retrieval/hybrid.py`)

## Why this / what's the need

Vector search (from earlier chapters) is great at finding text that *reads similarly* to
your question. The knowledge graph (Chapter 6) is great at finding *connections between
things* — who owns what, who depends on what. Neither one alone is the full picture.

Think of it like hiring for a job: you first ask a large recruiting agency to send you
every resume that *looks* like a decent fit (that's vector search + graph search
together — cast a wide net, get lots of candidates). But a big pile of "looks okay"
resumes still needs a **picky, careful second reviewer** who actually reads every one
side-by-side with the job description and re-orders them by who's *really* the best
fit. That pickier reviewer is what a **re-ranker** does in this project — it's a second
opinion that looks more carefully than the first, faster pass.

> 🔑 **New word — re-ranker:** a second, more careful model that takes a list of already
> -found candidate answers and re-orders them by how relevant each one really is to the
> question — a "quality control" pass after the wide-net search.

> 🔑 **New word — cross-encoder:** a specific kind of re-ranker model that reads the
> question AND one candidate answer *together, at the same time*, so it can judge their
> match much more precisely than a quick similarity score can. (The trade-off: it's
> slower, so it's only run on the smaller, already-narrowed-down candidate list — not
> on the whole knowledge base.)

`app/retrieval/hybrid.py` is the file that ties vector search + graph search + the
cross-encoder re-ranker together into one function: `hybrid_search()`.

## The whole pipeline, step by step

### Step 1 — Run vector search

```python
try:
    from app.retrieval.vector_search import get_searcher

    vsearcher = get_searcher()
    vresults = vsearcher.search(query, k=vector_k or settings.retrieval_top_k)
    for r in vresults:
        candidates.append({
            "text": r["text"],
            "metadata": r["metadata"],
            "score": r["score"],
            "source": "vector",
        })
except Exception as exc:
    log.warning("hybrid_vector_search_failed", error=str(exc))
```

- Calls the ChromaDB-backed vector searcher from earlier chapters, gets back the top
  matching text chunks, and tags each one `"source": "vector"` so later code always
  knows where a result came from.
- Wrapped in `try/except` — if vector search fails for any reason, the whole hybrid
  search doesn't crash; it just logs a warning and moves on with whatever it has.

### Step 2 — Run graph search (the previous chapter's `GraphSearcher`)

```python
if use_graph:
    try:
        from app.retrieval.graph_search import get_graph_searcher

        gsearcher = get_graph_searcher()
        gresults = gsearcher.search(query, k=graph_k or settings.retrieval_top_k)
        for r in gresults:
            candidates.append({
                "text": r["text"],
                "metadata": r["metadata"],
                "score": r["score"],
                "source": "graph",
            })
    except Exception as exc:
        log.warning("hybrid_graph_search_failed", error=str(exc))
```

- Same idea, but pulling plain-English relationship sentences (e.g. "Payment-Service
  depends on Auth-DB.") from Neo4j, tagged `"source": "graph"`.
- `use_graph: bool = True` — a function parameter lets a caller skip graph search
  entirely if needed (e.g. for a quick vector-only test).
- Because both results end up in the exact same shape (`text`, `metadata`, `score`,
  `source`), the rest of the function doesn't need to know or care which kind of search
  produced which candidate — this is **merging vector + graph results**: putting two
  different retrieval methods' outputs into one single list to be treated identically
  from here on.

### Step 3 — Deduplicate

```python
def _dedup_candidates(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for c in candidates:
        key = c["text"].strip().lower()[:300]
        if key in seen:
            continue
        seen.add(key)
        out.append(c)
    return out
```

- Builds a `key` from the first 300 characters of each candidate's lowercased text.
- If two candidates have (near-)identical text — most commonly two overlapping vector
  chunks — only the first one is kept. Vector and graph results rarely duplicate each
  other in practice (one is prose, the other is short relationship sentences), but
  vector search alone can occasionally return near-duplicate chunks.

### Step 4 — Re-rank the merged, deduped list with the cross-encoder

```python
@lru_cache(maxsize=1)
def _get_cross_encoder():
    from sentence_transformers import CrossEncoder
    log.info("loading_cross_encoder", model=settings.rerank_model)
    return CrossEncoder(settings.rerank_model)
```

- `settings.rerank_model` is `cross-encoder/ms-marco-MiniLM-L-6-v2` — a small, local
  cross-encoder model (downloaded once, then runs on your own machine — no API call).
- `@lru_cache(maxsize=1)` — loads this model into memory only once and reuses it for
  every future call, since loading a model from disk is relatively slow/expensive and
  there's no reason to repeat it every search.

```python
if use_rerank and len(candidates) > 1:
    try:
        ce = _get_cross_encoder()
        pairs = [(query, c["text"]) for c in candidates]
        ce_scores = ce.predict(pairs)
        for c, s in zip(candidates, ce_scores):
            c["rerank_score"] = float(s)
        candidates.sort(key=lambda c: c["rerank_score"], reverse=True)
        for c in candidates:
            c["score"] = c["rerank_score"]
    except Exception as exc:
        log.warning("rerank_failed_falling_back_to_raw_scores", error=str(exc))
        candidates.sort(key=lambda c: c["score"], reverse=True)
```

- `pairs = [(query, c["text"]) for c in candidates]` — builds a `(question, candidate
  text)` pair for **every single candidate**. This is the defining trait of a
  cross-encoder: it looks at the question and one candidate *together* in a single pass,
  rather than comparing two separately-computed number vectors (which is what the
  earlier, faster vector search does). Reading them together lets it judge relevance
  much more precisely — like actually reading a resume next to the job posting, instead
  of just checking if similar keywords appear.
- `ce.predict(pairs)` — runs the model once over all pairs and returns a relevance score
  per pair.
- `candidates.sort(key=lambda c: c["rerank_score"], reverse=True)` — re-orders the whole
  list by this new, more careful score, best first.
- If re-ranking itself fails for any reason (e.g. the model can't load), it falls back
  to sorting by the original vector/graph scores instead of crashing — another
  "degrade, don't crash" pattern.
- Note the docstring's warning: after re-ranking, `score` is the cross-encoder's
  relevance score — it is **not** directly comparable to the raw vector similarity or
  graph confidence scores that were there before Step 4. Once re-ranked, all candidates
  share one consistent scoring scale.

### Step 5 — Trim to the top N and finalize

```python
top = candidates[:top_n]
for i, c in enumerate(top):
    c["rank"] = i + 1
    c.pop("rerank_score", None)
    c["score"] = float(c["score"])  # numpy float32 (from cross-encoder) -> native float
```

- `top_n` (from `settings.hybrid_top_n` by default) — only the best few candidates are
  kept and passed on to the agent; the LLM answering the question doesn't need to read
  every single retrieved chunk, just the most relevant handful.
- `float(c["score"])` — the cross-encoder library returns NumPy `float32` numbers, which
  don't serialize cleanly to JSON; converting to a native Python `float` avoids that.

## Why bother with two search methods AND a re-ranker?

- Vector search alone: fast, good at "reads similarly," but blind to explicit
  relationships between named things.
- Graph search alone: great at relationships, but blind to anything not already
  captured as a named entity/relationship (most of a document's actual prose).
- Cross-encoder re-ranking on top of both: since vector similarity scores and graph
  "confidence" scores (a flat `0.75` — see Chapter 6) aren't even on the same scale to
  begin with, something has to fairly judge the *combined* candidate pool against the
  actual question. That's the re-ranker's job — it's the one step that looks at
  everything through the same, consistent lens.

## ✅ You just learned
- What **merging vector + graph results** means: normalizing both into the same
  `{text, metadata, score, source}` shape so they can be treated identically afterward.
- What a **re-ranker** / **cross-encoder** is, and why reading question+candidate
  together (instead of comparing separate embeddings) produces a more accurate but
  slower relevance judgment — which is why it only runs on the small, already-narrowed
  candidate list.
- The full `hybrid_search()` pipeline: vector search → graph search → dedup → 
  cross-encoder rerank → trim to top N.
- The project's repeated "degrade, don't crash" pattern: if vector search, graph search,
  or re-ranking fails, the pipeline logs a warning and keeps going with what it has.

## ▶️ Run this now
`hybrid.py` has nothing to run standalone — it's a library used by the `retrieve` agent
tool (Chapter 8) and the API. You can exercise it directly from a Python shell to see it
work end-to-end:
```
.venv\Scripts\python.exe -c "from app.retrieval.hybrid import hybrid_search; import json; print(json.dumps(hybrid_search('If Payment-Service goes down, who do I contact?', k=5), indent=2))"
```

## 🧠 Check yourself
1. Why is a cross-encoder only run on the already-retrieved candidates instead of the
   entire knowledge base?
2. After re-ranking, is a candidate's `score` field still directly comparable to a raw
   vector-search similarity score? Why or why not?
3. If `use_graph=False` were passed to `hybrid_search()`, what would change about the
   candidate list going into the re-ranker?

Continue to the next chapter → 08-agent-and-tools.md
