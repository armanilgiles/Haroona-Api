from __future__ import annotations

import argparse
import json
import statistics
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from urllib.parse import urljoin


@dataclass(frozen=True)
class BenchmarkResult:
    path: str
    requests: int
    successful: int
    p50_ms: float | None
    p95_ms: float | None
    mean_ms: float | None
    mean_payload_bytes: float | None
    server_timing: str | None


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, round((len(ordered) - 1) * percentile)))
    return ordered[index]


def benchmark_path(
    *,
    base_url: str,
    path: str,
    requests: int,
    warmup: int,
    timeout_seconds: float,
) -> BenchmarkResult:
    url = urljoin(f"{base_url.rstrip('/')}/", path.lstrip("/"))

    for _ in range(warmup):
        try:
            with urllib.request.urlopen(url, timeout=timeout_seconds) as response:
                response.read()
        except (urllib.error.URLError, TimeoutError):
            pass

    durations: list[float] = []
    payload_sizes: list[int] = []
    latest_server_timing: str | None = None
    for _ in range(requests):
        started = time.perf_counter()
        try:
            with urllib.request.urlopen(url, timeout=timeout_seconds) as response:
                payload = response.read()
                duration_ms = (time.perf_counter() - started) * 1000
                if 200 <= response.status < 300:
                    durations.append(duration_ms)
                    payload_sizes.append(len(payload))
                    latest_server_timing = response.headers.get("Server-Timing")
        except (urllib.error.URLError, TimeoutError):
            continue

    return BenchmarkResult(
        path=path,
        requests=requests,
        successful=len(durations),
        p50_ms=_percentile(durations, 0.50),
        p95_ms=_percentile(durations, 0.95),
        mean_ms=statistics.fmean(durations) if durations else None,
        mean_payload_bytes=(statistics.fmean(payload_sizes) if payload_sizes else None),
        server_timing=latest_server_timing,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark Haroona API endpoints")
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--path", action="append", required=True)
    parser.add_argument("--requests", type=int, default=30)
    parser.add_argument("--warmup", type=int, default=3)
    parser.add_argument("--timeout", type=float, default=15.0)
    args = parser.parse_args()

    if args.requests < 1 or args.warmup < 0 or args.timeout <= 0:
        parser.error("requests/timeout must be positive and warmup cannot be negative")

    results = [
        benchmark_path(
            base_url=args.base_url,
            path=path,
            requests=args.requests,
            warmup=args.warmup,
            timeout_seconds=args.timeout,
        )
        for path in args.path
    ]
    print(json.dumps([asdict(result) for result in results], indent=2))


if __name__ == "__main__":
    main()
