# Performance / Load Test — Enterprise Knowledge Assistant

_Generated: 2026-07-01T19:18:43+00:00_

- Total requests: 24 (concurrency 4)
- Successful: 24  |  Failed: 0
- Wall time: 58.7s  |  Throughput: 0.41 req/s

## Latency (successful requests)

| Metric | Seconds |
|---|---|
| mean | 9.62 |
| p50 | 2.81 |
| p95 | 35.69 |
| p99 | 39.52 |
| min | 2.22 |
| max | 39.52 |

## Semantic cache effect

| Bucket | Count | Mean latency (s) |
|---|---|---|
| cache miss | 5 | 27.83 |
| cache hit | 19 | 4.83 |

**Cache speedup: ~6x faster on hits.**
