# Performance checks

Every API response includes a `Server-Timing` header with total application
time, database time, and query count. Requests slower than
`PERF_SLOW_REQUEST_MS` (default `750`) are logged. Set
`PERF_LOG_REQUESTS=true` temporarily to log every request.

Cities, countries, brands, and feed filter metadata return a content-derived
ETag plus `Cache-Control: public, max-age=60, must-revalidate`. Browsers and
CDNs may reuse them for one minute, then must revalidate. Publish, unpublish,
archive, category, city, brand, and logo changes produce a different ETag on
the next request, so invalidation is bounded to the 60-second freshness window
without a cache-flush service. Product pages, prices, inventory, admin data,
and user data are not covered by this reference-data cache.

Run a repeatable local or deployed comparison:

```bash
python -m app.scripts.benchmark_api \
  --base-url http://127.0.0.1:8000 \
  --path '/feed/products?limit=24' \
  --path '/feed/filters' \
  --path '/search?q=linen' \
  --requests 30 \
  --warmup 3
```

The command reports success count, p50, p95, mean latency, mean payload bytes,
and the latest `Server-Timing` value. Compare the same database snapshot,
worker count, endpoint parameters, and network location before and after a
deployment.

For PostgreSQL query plans, capture representative production parameters and
run `EXPLAIN (ANALYZE, BUFFERS)` during a low-risk maintenance window. Do not
infer production plans from SQLite tests.
