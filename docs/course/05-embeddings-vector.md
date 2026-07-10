# Chapter 5 — Turning Text into Searchable Meaning: Embeddings, Chunking, and Vector Search

## Why this / what's the need

Imagine trying to find "who owns the Payment-Service?" by literally searching for those
exact words across hundreds of documents. If a document says "Priya Sharma leads the
Billing team, which is responsible for Payment-Service" but never uses the word "owns,"
a plain keyword search misses it completely. What we actually want is search by
*meaning*, not exact wording — like asking a librarian who has read every book and can
point you to the right page even if you don't use the book's exact phrasing.

That's what this trio of files does:
- `app/retrieval/embeddings.py` — turns text into a list of numbers that captures its
  meaning (and makes sure indexing and searching always use the *same* method).
- `app/ingestion/chunker.py` — cuts long documents into bite-sized pieces (because
  meaning-search works better on paragraphs than whole PDFs) and stores them.
- `app/retrieval/vector_search.py` — given a question, finds the most meaningfully
  similar stored pieces.

> 🔑 **New word — embedding:** a list of numbers (a vector) that represents the
> *meaning* of a piece of text, produced by a machine learning model — texts with
> similar meaning end up with similar numbers.

> 🔑 **New word — vector:** just a list of numbers, like `[0.12, -0.87, 0.33, ...]` —
> here, the numeric "fingerprint" of a piece of text's meaning.

## `embeddings.py` — one shared way to turn text into vectors

```python
from app.config import get_settings
settings = get_settings()

@lru_cache(maxsize=1)
def get_embedding_function():
    from chromadb.utils import embedding_functions

    if settings.embedding_provider == "local":
        return embedding_functions.ONNXMiniLM_L6_V2()
    else:
        kwargs: dict[str, Any] = {
            "api_key": settings.openai_api_key,
            "model_name": settings.embedding_model,
        }
        if settings.openai_base_url:
            kwargs["api_base"] = settings.openai_base_url
        return embedding_functions.OpenAIEmbeddingFunction(**kwargs)
```

- `settings = get_settings()` — grabs the one shared settings object from Chapter 3, so
  this file doesn't need to read `.env` itself.
- `@lru_cache(maxsize=1)` on `get_embedding_function()` — same singleton trick as
  `get_settings()`: build the embedding function once, reuse it everywhere, instead of
  reloading a model repeatedly.
- `if settings.embedding_provider == "local":` — this is the important branch for this
  project. It returns `ONNXMiniLM_L6_V2()`, a small embedding model bundled with
  **ChromaDB** that runs entirely on your own machine — no API key, no internet call, no
  cost. This project uses `"local"` specifically because **OpenRouter (used for chat)
  doesn't offer an embeddings endpoint**, so text-to-vector conversion has to happen
  locally instead.
- The `else` branch — shows how it *would* call a real OpenAI-compatible embeddings API
  if `embedding_provider` were set to anything else, using the API key and optional
  `openai_base_url` from settings. It's kept for completeness/future use but isn't the
  path this project runs on.

> 🔑 **New word — ONNX:** a standard, portable format for machine learning models that
> lets them run quickly on a normal computer without needing specialized cloud hardware.

```python
def get_chroma_collection():
    import chromadb

    client = chromadb.PersistentClient(path=str(settings.chroma_persist_path))
    collection = client.get_or_create_collection(
        name=settings.chroma_collection_name,
        metadata={"hnsw:space": "cosine"},
        embedding_function=get_embedding_function(),
    )
    return collection
```

- `chromadb.PersistentClient(path=...)` — opens (or creates) a **ChromaDB** database
  saved to disk at the folder from `settings.chroma_persist_path`, so your indexed data
  survives between runs instead of disappearing when the script ends.
- `client.get_or_create_collection(...)` — opens the named collection (a table-like
  bucket of vectors) if it exists, or creates it fresh if not.
- `metadata={"hnsw:space": "cosine"}` — tells Chroma to measure "how similar are two
  vectors?" using **cosine similarity**, the standard way to compare meaning-vectors.
- `embedding_function=get_embedding_function()` — this is the crucial part: by binding
  the *same* embedding function to the collection, both indexing (`chunker.py`) and
  searching (`vector_search.py`) automatically use identical embedding logic. If they
  ever used different embedding methods, search results would be meaningless.

> 🔑 **New word — cosine similarity:** a way to measure how similar two vectors' *direction*
> is, regardless of their length — the standard method for comparing meaning-vectors; 1.0
> means identical meaning, 0 means unrelated.

> 🔑 **New word — collection (in ChromaDB):** a named bucket of stored vectors, similar
> to a table in a regular database.

## `chunker.py` — cutting documents into searchable pieces

```python
def recursive_split(text: str, chunk_size: int = 500, chunk_overlap: int = 50) -> list[str]:
    separators = ["\n\n", "\n", ". ", " ", ""]

    def _split(text: str, seps: list[str]) -> list[str]:
        if not seps or _estimate_tokens(text) <= chunk_size:
            return [text] if text.strip() else []
        sep = seps[0]
        parts = text.split(sep) if sep else list(text)
        ...
```

- `_estimate_tokens(text)` — a rough rule of thumb (`len(text) // 4`) for guessing how
  many "tokens" a chunk of text will use, without needing an actual tokenizer.
- `recursive_split(...)` — the core chunking logic. It tries splitting the text on the
  biggest, most natural boundary first (`"\n\n"`, a blank line between paragraphs); if a
  resulting piece is still too big, it recurses and tries a smaller boundary (single
  newline, then sentence-ending `". "`, then plain spaces, then individual characters as
  a last resort).
- The `for part in parts:` loop — walks through the split pieces, gluing them back
  together into a `current` chunk as long as it stays under `chunk_size` tokens (default
  **500**, from Chapter 3's settings); once adding another piece would go over, it seals
  off the current chunk and starts a new one.
- `overlap_text = current[-chunk_overlap * 4:]` — before starting the next chunk, it
  carries over the last `chunk_overlap` tokens' worth of characters (default **50**) from
  the previous chunk. This overlap means a fact that lands right at a chunk boundary
  still appears whole in at least one chunk, instead of being awkwardly cut in half.

> 🔑 **New word — chunk:** a smaller piece of a longer document, split so it's short
> enough for the embedding model to handle well and focused enough for search to be precise.

> 🔑 **New word — token:** a small unit of text (often close to a word or word-piece)
> that language models process one at a time — used here just as a rough size measure.

```python
def chunk_document(doc: dict[str, Any]) -> list[dict[str, Any]]:
    text = doc["text"]
    meta = doc["metadata"]
    chunks_text = recursive_split(text, settings.chunk_size, settings.chunk_overlap)
    chunks = []
    for i, chunk in enumerate(chunks_text):
        chunk_meta = {**meta, "chunk_index": i, "total_chunks": len(chunks_text)}
        chunks.append({"id": f"{meta['source']}_chunk_{i}", "text": chunk, "metadata": chunk_meta})
    return chunks
```

- `chunk_document(doc)` — takes one loaded document (from `loader.py` in Chapter 4) and
  splits its `text` into pieces, while copying the original document's `metadata` (source
  filename, doc type, etc.) onto every chunk so you never lose track of where a chunk
  came from.
- `chunk_meta = {**meta, "chunk_index": i, "total_chunks": len(chunks_text)}` — adds two
  extra fields recording this chunk's position (e.g. "chunk 2 of 5") within its parent
  document.
- `"id": f"{meta['source']}_chunk_{i}"` — builds a unique ID per chunk, like
  `INC-204.md_chunk_0`, so ChromaDB can store and reference each piece individually.

```python
def build_index(raw_dir: Path | None = None) -> None:
    docs = load_all(raw_dir)
    all_chunks = []
    for doc in docs:
        all_chunks.extend(chunk_document(doc))

    collection = get_chroma_collection()
    existing_count = collection.count()
    if existing_count > 0:
        print(f"[chunker] Collection already has {existing_count} embeddings. Skipping re-index.")
        return

    texts = [c["text"] for c in all_chunks]
    ids = [c["id"] for c in all_chunks]
    metadatas = [c["metadata"] for c in all_chunks]

    BATCH = 500
    for start in range(0, len(ids), BATCH):
        collection.add(ids=ids[start:start+BATCH], documents=texts[start:start+BATCH], metadatas=metadatas[start:start+BATCH])
```

- `docs = load_all(raw_dir)` — reuses `loader.py` from Chapter 4 to load every raw
  document into memory.
- The `for doc in docs:` loop — chunks every document and collects all resulting chunks
  into one flat `all_chunks` list.
- `collection = get_chroma_collection()` — opens the shared ChromaDB collection from
  `embeddings.py` above.
- `if existing_count > 0: ... return` — a safety guard: if the collection already has
  data in it, skip re-indexing (and tell you to delete `data/chroma_db/` if you actually
  want to rebuild from scratch). This avoids accidentally duplicating every chunk if you
  run the script twice.
- `collection.add(ids=..., documents=texts, metadatas=...)` — hands Chroma the raw chunk
  **text** (not pre-computed vectors!). Chroma uses the `embedding_function` bound to the
  collection to embed the text itself, right at insert time — this is exactly why
  binding one shared embedding function in `embeddings.py` matters: the same function
  will later embed your *search query* the same way.
- `BATCH = 500` / the `for start in range(0, len(ids), BATCH):` loop — inserts chunks 500
  at a time instead of all at once, which is gentler on memory and avoids potential
  request-size limits.

## `vector_search.py` — asking a question and getting the closest chunks

```python
class VectorSearcher:
    def __init__(self) -> None:
        self._collection = None

    def _get_collection(self):
        if self._collection is None:
            try:
                self._collection = get_chroma_collection()
            except Exception:
                raise RuntimeError(
                    f"ChromaDB collection '{settings.chroma_collection_name}' not found. "
                    "Run: python -m app.ingestion.chunker"
                )
        return self._collection
```

- `class VectorSearcher:` — a small class that wraps a ChromaDB collection for
  searching.
- `self._collection = None` in `__init__` — the collection isn't opened immediately when
  the object is created; it's opened **lazily**, only the first time it's actually
  needed. This avoids unnecessary work (and unnecessary errors) if a `VectorSearcher` is
  created but never used.
- `_get_collection()` — opens the collection on first use and caches it on `self`; if
  opening fails (e.g. you never ran the chunker), it raises a clear error telling you
  exactly which command to run to fix it.

> 🔑 **New word — lazy initialization:** delaying setup work until the moment it's
> actually needed, instead of doing it upfront every time.

```python
    def search(self, query: str, k: int | None = None, filters: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        top_k = k or settings.retrieval_top_k
        collection = self._get_collection()
        if collection.count() == 0:
            raise RuntimeError("ChromaDB collection is empty. Run: python -m app.ingestion.chunker")

        kwargs: dict[str, Any] = {
            "query_texts": [query],
            "n_results": min(top_k, collection.count()),
            "include": ["documents", "metadatas", "distances"],
        }
        if filters:
            kwargs["where"] = filters
        results = collection.query(**kwargs)
```

- `top_k = k or settings.retrieval_top_k` — use the caller's requested number of results,
  or fall back to the default from settings (Chapter 3's `retrieval_top_k = 5`).
- `if collection.count() == 0: raise RuntimeError(...)` — another friendly guard: an
  empty database means "you forgot to index anything," so it says so directly rather
  than returning a confusing empty result.
- `"query_texts": [query]` — this is the key line: it passes the raw question text, not
  a pre-computed vector. ChromaDB embeds the query using the *same* bound embedding
  function used at index time, guaranteeing the query and the stored chunks live in the
  same "meaning space" and can be meaningfully compared.
- `"include": ["documents", "metadatas", "distances"]` — asks Chroma to return the
  original chunk text, its metadata, and a distance score for each match.
- `if filters: kwargs["where"] = filters` — optionally narrows the search, e.g. only
  search chunks where `doc_type == "policy"`.

```python
        docs = results.get("documents", [[]])[0]
        metas = results.get("metadatas", [[]])[0]
        distances = results.get("distances", [[]])[0]

        output: list[dict[str, Any]] = []
        for rank, (text, meta, dist) in enumerate(zip(docs, metas, distances)):
            score = 1.0 - dist
            output.append({"text": text, "metadata": meta, "score": round(score, 4), "rank": rank + 1})
        return output
```

- `results.get("documents", [[]])[0]` — Chroma returns results as a list-of-lists (one
  inner list per query); since only one query text was sent, `[0]` unwraps it to the flat
  list of matched chunk texts. Same idea for `metas` and `distances`.
- `score = 1.0 - dist` — Chroma returns *distance* (lower = more similar, since the
  collection uses cosine space); flipping it to `1.0 - dist` turns it into an intuitive
  *similarity* score where higher = better match.
- The final loop — builds the list of result dictionaries with `text`, `metadata`,
  `score`, and `rank` (1st best, 2nd best, ...), ready for the rest of the app (or you)
  to read.

```python
@lru_cache(maxsize=1)
def get_searcher() -> VectorSearcher:
    """Module-level cached searcher singleton."""
    return VectorSearcher()
```

- Same singleton pattern as `get_settings()` and `get_embedding_function()` — one shared
  `VectorSearcher` for the whole app, built once.

## ✅ You just learned

- What an embedding is and why searching by meaning beats exact keyword matching.
- Why this project embeds locally (ChromaDB's ONNX MiniLM model) instead of via
  OpenRouter — OpenRouter has no embeddings endpoint, and local is free and private.
- How `recursive_split` breaks documents into ~500-token chunks with 50-token overlap so
  facts near chunk boundaries aren't lost.
- Why indexing and searching must share one embedding function (`get_chroma_collection`)
  — otherwise queries and stored chunks wouldn't be comparable.
- How `VectorSearcher.search()` turns a plain question into ranked, scored chunk matches.

## ▶️ Run this now

First build the index (only needs to be done once, or after deleting `data/chroma_db/`):

```powershell
.venv\Scripts\python.exe -m app.ingestion.chunker
```

Then try a real search from the command line:

```powershell
.venv\Scripts\python.exe -c "from app.retrieval.vector_search import get_searcher; [print(r['rank'], r['score'], r['text'][:80]) for r in get_searcher().search('Who owns the Payment-Service?')]"
```

## 🧠 Check yourself

1. Why does `get_chroma_collection()` bind the same `embedding_function` for both
   indexing and searching, instead of letting each file pick its own?
2. What problem does `chunk_overlap` (50 tokens) solve when splitting long documents?
3. If you ran `python -m app.ingestion.chunker` twice in a row, what would happen the
   second time, and why?

Continue to the next chapter → [06-knowledge-graph.md](06-knowledge-graph.md)
