# Chapter 10 — Routing and Caching: Spend Money Wisely, Don't Repeat Yourself

## Why this / what's the need

Picture a help desk with two staff members: a junior clerk who's fast and cheap, and a senior expert who's slower and costs more per hour. You wouldn't send "what are your opening hours?" to the senior expert — that's a waste of their time and your money. You'd only escalate the genuinely tricky, multi-step questions to them. That's **model routing**.

Now picture that same help desk keeping a notebook of every question they've already answered. If someone asks "what time do you open?" and someone else asks "when do you open in the morning?" — those are the *same question* worded differently. Instead of re-answering from scratch, the clerk flips to the notebook and reuses yesterday's answer. That's a **semantic cache** — it remembers answers by *meaning*, not by exact wording.

Both of these exist for the same reason: AI calls to models like GPT-4o cost real money and take real time. Every unnecessary call to the expensive model, or every repeated question that gets fully re-processed, is wasted cost and wasted latency.

> 🔑 **New word — latency:** The delay between asking a question and getting the answer back. Lower latency = feels faster.

This chapter covers two files:
- `app/routing/model_router.py` — picks the cheap model vs. the smart model per question.
- `app/caching/semantic_cache.py` — remembers and reuses past answers for similarly-worded questions.

---

## Part 1 — Model Routing (`app/routing/model_router.py`)

The app has two models configured: a cheap default (`gpt-4o-mini`) and a stronger, pricier one (`gpt-4o`). The router's job is to decide, per question, which one to use.

### Scoring how "complex" a question is

```python
_MULTI_HOP_PATTERNS = [
    r"\band\b.*\bwho\b", r"\band\b.*\bwhat\b", r"\bif\b.*\bthen\b",
    r"\bdepends? on\b", r"\bwho (do i|should i) (contact|call|escalate)\b",
    r"\bwhy\b.*\bcaused?\b", r"\bcompare\b", r"\bdifference between\b",
    r"\bstep[s]? (to|for)\b", r"\bwhat.*and.*who\b", r"\bhow many\b.*\band\b",
]
_MULTI_HOP_RE = re.compile("|".join(_MULTI_HOP_PATTERNS), re.IGNORECASE)
```
- `_MULTI_HOP_PATTERNS` — a list of regex patterns that tend to show up in questions requiring several logical steps to answer, e.g. "X and who approved it?" or "what's the difference between A and B?" These are called **multi-hop** questions because answering them means following more than one chain of reasoning.
- `_MULTI_HOP_RE = re.compile(...)` — combines them into one matcher, case-insensitive.

```python
_TOOL_NEED_PATTERNS = [
    r"\bsum\b", r"\btotal\b", r"\baverage\b", r"\bcount\b", r"\bcalculate\b",
    r"\bhow much\b", r"\bhow many\b", r"\btop \d+\b", r"\bquery\b",
]
_TOOL_NEED_RE = re.compile("|".join(_TOOL_NEED_PATTERNS), re.IGNORECASE)

_LONG_QUERY_CHAR_THRESHOLD = 220
_LONG_QUERY_WORD_THRESHOLD = 35
```
- `_TOOL_NEED_PATTERNS` — words like "sum," "average," "top 5" suggest the question probably needs actual calculation or database querying, not just fact lookup — a sign it needs a smarter model.
- `_LONG_QUERY_CHAR_THRESHOLD` / `_LONG_QUERY_WORD_THRESHOLD` — a question longer than 220 characters or 35 words is treated as a sign of complexity too (people usually write more when the question is genuinely complicated).

```python
def _complexity_score(query: str) -> tuple[int, list[str]]:
    score = 0
    reasons: list[str] = []

    n_chars = len(query)
    n_words = len(query.split())

    if n_chars > _LONG_QUERY_CHAR_THRESHOLD or n_words > _LONG_QUERY_WORD_THRESHOLD:
        score += 1
        reasons.append("long_query")

    if _MULTI_HOP_RE.search(query):
        score += 2
        reasons.append("multi_hop_indicator")

    if _TOOL_NEED_RE.search(query):
        score += 1
        reasons.append("tool_need_indicator")

    if query.count("?") > 1:
        score += 1
        reasons.append("multiple_questions")
    if len(re.findall(r"\band\b", query, re.IGNORECASE)) >= 2:
        score += 1
        reasons.append("multiple_conjunctions")

    return score, reasons
```
- Each signal adds points to a running `score`: length (+1), a multi-hop pattern (+2 — weighted heaviest, since it's the strongest complexity signal), needing a tool/calculation (+1), more than one question mark (+1), two-or-more "and"s (+1).
- `reasons.append(...)` — every point added is logged with *why*, so later you can debug or audit which questions got routed where.
- `return score, reasons` — hands back both the number and the explanation.

### Making the decision

```python
def route_model(query: str, threshold: int = 2) -> tuple[str, dict]:
    score, reasons = _complexity_score(query)
    if score >= threshold:
        model = settings.llm_advanced_model
        tier = "advanced"
    else:
        model = settings.llm_default_model
        tier = "default"

    info = {"score": score, "reasons": reasons, "tier": tier}
    log.info("model_routed", model=model, score=score, tier=tier, reasons=reasons)
    return model, info
```
- `threshold: int = 2` — the cutoff: a score of 2 or more sends the question to the advanced (expensive) model; below that, it stays on the cheap default.
- `if score >= threshold: model = settings.llm_advanced_model` — e.g. any single multi-hop match alone (worth 2 points) is enough to trigger the smart model.
- `else: model = settings.llm_default_model` — everything else (most simple factual questions) goes to the cheap model, `gpt-4o-mini`.
- `log.info("model_routed", ...)` — records every routing decision, so you can later see, in aggregate, how often the expensive model gets used (and whether the thresholds need tuning).
- Returns both the chosen model name *and* the `info` dict explaining the decision — useful for debugging and for showing users/admins why a particular model was picked.

---

## Part 2 — Semantic Caching (`app/caching/semantic_cache.py`)

### The idea

> 🔑 **New word — cache:** A place that stores an answer you already computed, so next time the same (or similar) request comes in, you can hand back the stored answer instantly instead of redoing the work.

A normal cache only matches *exact* repeated text. A **semantic cache** is smarter — it matches by *meaning*. "What are your office hours?" and "When do you open?" are different words but the same underlying question, and a semantic cache treats them as the same.

> 🔑 **New word — cosine similarity:** A mathematical way to measure how "close" two pieces of meaning are, by comparing their embedding vectors. A score of 1.0 means identical meaning; 0.0 means totally unrelated.

To compare meanings, the code first turns each question into an **embedding** — a list of numbers that represents its meaning — then measures the angle between two questions' number-lists with cosine similarity.

```python
def _cosine_similarity(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)
```
- `dot = sum(x * y for x, y in zip(a, b))` — multiplies matching positions of the two number-lists and adds them up (the "dot product").
- `norm_a`, `norm_b` — the "length" of each vector.
- `return dot / (norm_a * norm_b)` — dividing the dot product by both lengths gives a number between -1 and 1 that captures how aligned in meaning the two questions are, regardless of their raw wording.

### Storage: fakeredis

> 🔑 **New word — cold start:** The delay/limitation of setting up a real service (like a Redis server) before your app can even run. Using a stand-in avoids that setup cost during development.

```python
def _get_redis(self):
    if self._redis is None:
        import fakeredis
        self._redis = fakeredis.FakeStrictRedis(decode_responses=True)
    return self._redis
```
- `fakeredis.FakeStrictRedis(...)` — Redis is normally a separate server you'd need to install and run. `fakeredis` is a Python library that pretends to be Redis but lives entirely inside your app's own memory — no installation, no server, no cold start. It's swapped in here specifically so this teaching project runs with zero extra setup, while keeping the exact same code shape you'd use with real Redis in production.

### Looking up a cached answer: `SemanticCache.get`

```python
def get(self, query: str) -> dict[str, Any] | None:
    if not settings.semantic_cache_enabled:
        return None
    try:
        r = self._get_redis()
        keys = r.smembers(_INDEX_KEY)
        if not keys:
            return None

        query_vec = self._embed(query)
        best_score = -1.0
        best_entry = None

        now = time.time()
        for key in keys:
            raw = r.get(key)
            if raw is None:
                r.srem(_INDEX_KEY, key)
                continue
            entry = json.loads(raw)
            if entry.get("expires_at", float("inf")) < now:
                r.delete(key)
                r.srem(_INDEX_KEY, key)
                continue
            score = _cosine_similarity(query_vec, entry["embedding"])
            if score > best_score:
                best_score = score
                best_entry = entry

        if best_entry is not None and best_score >= self.threshold:
            payload = dict(best_entry["payload"])
            payload["cache_hit"] = True
            payload["cache_similarity"] = round(best_score, 4)
            payload["cached_query"] = best_entry["query_text"]
            return payload

        return None
    except Exception as exc:
        log.warning("semantic_cache_get_failed", error=str(exc))
        return None
```
- `if not settings.semantic_cache_enabled: return None` — the cache can be turned off entirely via config; when off, every lookup is a miss (forces a fresh AI call).
- `query_vec = self._embed(query)` — turns the incoming question into its number-list "meaning fingerprint."
- The `for key in keys:` loop walks every previously cached question, skips expired ones (`entry.get("expires_at", ...) < now`), and computes cosine similarity against each.
- `if best_entry is not None and best_score >= self.threshold:` — only returns a cached answer if the *best* match's similarity meets or beats the threshold — configured in this project as **0.92** (very high similarity required, to avoid returning a wrong-but-similar-sounding cached answer).
- `payload["cache_hit"] = True` — tags the returned answer so the rest of the app (and you, when debugging) can tell it came from cache, not a fresh AI call.
- `except Exception as exc: ... return None` — any failure (corrupted entry, embedding error) just falls back to "no cache hit," never crashes the request.

### Saving an answer: `SemanticCache.set`

```python
def set(self, query: str, payload: dict[str, Any]) -> None:
    if not settings.semantic_cache_enabled:
        return
    try:
        r = self._get_redis()
        query_vec = self._embed(query)
        key = f"{_CACHE_KEY_PREFIX}{abs(hash(query))}_{int(time.time() * 1000)}"
        entry = {
            "query_text": query,
            "embedding": query_vec,
            "payload": payload,
            "expires_at": time.time() + self.ttl_s,
        }
        r.set(key, json.dumps(entry, default=_json_default), ex=self.ttl_s)
        r.sadd(_INDEX_KEY, key)
    except Exception as exc:
        log.warning("semantic_cache_set_failed", error=str(exc))
```
- `query_vec = self._embed(query)` — stores the *meaning fingerprint*, not just the raw text, so future lookups can compare by meaning.
- `"expires_at": time.time() + self.ttl_s` — every cache entry expires after a set time-to-live (**3600 seconds = 1 hour**, by default), so stale answers don't live forever.
- `r.set(key, ..., ex=self.ttl_s)` — also tells fakeredis itself to auto-expire the key after that same time, as a backup expiry mechanism.
- `r.sadd(_INDEX_KEY, key)` — adds this entry's key to a master "index" set, so `get()` knows which keys exist to scan through.

### The shared singleton

```python
_cache: SemanticCache | None = None

def get_semantic_cache() -> SemanticCache:
    global _cache
    if _cache is None:
        _cache = SemanticCache()
    return _cache
```
- `get_semantic_cache()` — instead of creating a new cache object everywhere it's needed, the app builds one shared instance the first time it's asked for, and reuses that same instance afterward (a **singleton** pattern) — otherwise every part of the app would have its own separate, disconnected cache.

---

## ✅ You just learned
- Model routing scores a question's complexity with regex heuristics and sends only the harder ones (score ≥ 2) to the pricier `gpt-4o` model, keeping easy questions on cheap `gpt-4o-mini`.
- A semantic cache stores past answers keyed by the *meaning* of the question (via embeddings), not the exact words.
- Cosine similarity measures how close two meanings are; this project only reuses a cached answer above a 0.92 similarity threshold — deliberately strict, to avoid wrong reuse.
- fakeredis is a zero-install, in-memory stand-in for a real Redis server, used here to avoid extra setup while keeping production-shaped code.
- Cache entries expire automatically (1 hour TTL) so answers don't go stale forever.

## ▶️ Run this now

```
.venv\Scripts\python.exe
```

```python
from app.routing.model_router import route_model

model, info = route_model("What are your office hours?")
print(model, info)
# gpt-4o-mini {'score': 0, 'reasons': [], 'tier': 'default'}

model2, info2 = route_model("What is the difference between plan A and plan B, and who do I contact to switch?")
print(model2, info2)
# gpt-4o {'score': 3+, 'reasons': ['multi_hop_indicator', ...], 'tier': 'advanced'}
```

```python
from app.caching.semantic_cache import get_semantic_cache

cache = get_semantic_cache()
cache.set("What time do you open?", {"answer": "We open at 9am."})

hit = cache.get("When do you open in the morning?")
print(hit)
# {'answer': 'We open at 9am.', 'cache_hit': True, 'cache_similarity': 0.9x, ...}
```

## 🧠 Check yourself
1. Why is the "multi-hop" pattern match worth 2 points while most other signals are worth just 1?
2. Why is the semantic cache's similarity threshold set as high as 0.92 instead of something lower like 0.6?
3. What would happen (in terms of setup effort) if `fakeredis` were replaced with a real Redis server? Would the rest of the code need to change?

Continue to the next chapter → 11-observability.md
