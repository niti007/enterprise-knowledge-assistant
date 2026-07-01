"""
eval/load_test.py — Phase 2 (T12)
==================================
Lightweight load / performance test against the running FastAPI /chat endpoint.
Measures latency p50/p95/p99 and throughput under concurrency, and demonstrates
the effect of the semantic cache (repeated queries).

No external load tool needed (uses stdlib threads + requests). Requires the API
running on http://localhost:8001.

Run (app venv, API up):
    .venv\\Scripts\\python.exe -m eval.load_test
"""
from __future__ import annotations

import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
API = "http://localhost:8001/chat"

# Mix of distinct queries (cache misses) + repeats (cache hits) to show caching.
QUERIES = [
    "Who owns the Payment-Service?",
    "What SOP restores the Payment-Service?",
    "Which team manages the Data Warehouse?",
    "What does the Payment-Service depend on?",
    "Who is the incident lead for INC-204?",
    "Who owns the Payment-Service?",           # repeat -> cache hit
    "What SOP restores the Payment-Service?",   # repeat -> cache hit
    "What does the Payment-Service depend on?", # repeat -> cache hit
]

CONCURRENCY = 4
TOTAL_REQUESTS = 24


def _one(i: int) -> dict:
    q = QUERIES[i % len(QUERIES)]
    t0 = time.perf_counter()
    try:
        r = requests.post(API, json={"message": q, "session_id": f"load-{i}"}, timeout=180)
        dt = time.perf_counter() - t0
        ok = r.status_code == 200
        body = r.json() if ok else {}
        return {"ok": ok, "latency": dt, "cache_hit": bool(body.get("cache_hit")),
                "status": r.status_code}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "latency": time.perf_counter() - t0, "cache_hit": False,
                "error": str(exc)[:80]}


def pct(data: list[float], p: float) -> float:
    if not data:
        return 0.0
    data = sorted(data)
    k = int(round((p / 100) * (len(data) - 1)))
    return data[k]


def main() -> None:
    # Preflight
    try:
        requests.get("http://localhost:8001/health", timeout=10).raise_for_status()
    except Exception as exc:  # noqa: BLE001
        print(f"API not reachable at http://localhost:8001 — start it first. ({exc})")
        sys.exit(1)

    print(f"Load test: {TOTAL_REQUESTS} requests, concurrency={CONCURRENCY}\n")
    t_start = time.perf_counter()
    results: list[dict] = []
    with ThreadPoolExecutor(max_workers=CONCURRENCY) as ex:
        futs = [ex.submit(_one, i) for i in range(TOTAL_REQUESTS)]
        for j, f in enumerate(as_completed(futs), 1):
            res = f.result()
            results.append(res)
            tag = "HIT " if res.get("cache_hit") else "miss"
            print(f"  [{j:02d}/{TOTAL_REQUESTS}] ok={res['ok']} {tag} {res['latency']:.2f}s")
    wall = time.perf_counter() - t_start

    ok = [r for r in results if r["ok"]]
    lat = [r["latency"] for r in ok]
    hits = [r for r in ok if r["cache_hit"]]
    misses = [r for r in ok if not r["cache_hit"]]
    throughput = len(ok) / wall if wall else 0.0

    def _stat(rows):
        xs = [r["latency"] for r in rows]
        return statistics.mean(xs) if xs else 0.0

    lines = []
    lines.append("# Performance / Load Test — Enterprise Knowledge Assistant\n")
    lines.append(f"_Generated: {datetime.now(timezone.utc).isoformat(timespec='seconds')}_\n")
    lines.append(f"- Total requests: {len(results)} (concurrency {CONCURRENCY})")
    lines.append(f"- Successful: {len(ok)}  |  Failed: {len(results) - len(ok)}")
    lines.append(f"- Wall time: {wall:.1f}s  |  Throughput: {throughput:.2f} req/s\n")
    lines.append("## Latency (successful requests)\n")
    lines.append("| Metric | Seconds |")
    lines.append("|---|---|")
    if lat:
        lines.append(f"| mean | {statistics.mean(lat):.2f} |")
        lines.append(f"| p50 | {pct(lat, 50):.2f} |")
        lines.append(f"| p95 | {pct(lat, 95):.2f} |")
        lines.append(f"| p99 | {pct(lat, 99):.2f} |")
        lines.append(f"| min | {min(lat):.2f} |")
        lines.append(f"| max | {max(lat):.2f} |")
    lines.append("\n## Semantic cache effect\n")
    lines.append("| Bucket | Count | Mean latency (s) |")
    lines.append("|---|---|---|")
    lines.append(f"| cache miss | {len(misses)} | {_stat(misses):.2f} |")
    lines.append(f"| cache hit | {len(hits)} | {_stat(hits):.2f} |")
    if misses and hits and _stat(misses) > 0:
        speedup = _stat(misses) / max(_stat(hits), 1e-6)
        lines.append(f"\n**Cache speedup: ~{speedup:.0f}x faster on hits.**\n")

    out = ROOT / "docs" / "LOAD_TEST_REPORT.md"
    out.write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines[-16:]))
    print(f"\nReport written to {out}")


if __name__ == "__main__":
    main()
