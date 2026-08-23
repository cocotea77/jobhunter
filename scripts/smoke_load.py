"""Latency smoke test (Step 11): the honest, bounded kind.

This is a SMOKE test, not a stress test (the Step 11 document defines
both). It answers one modest question with real numbers: under a small
concurrent load, what latency do the cheap endpoints actually serve, and
does anything fail? Run it against local or production:

    python scripts/smoke_load.py --url http://localhost:8000
    python scripts/smoke_load.py --url https://<backend>.up.railway.app --requests 100

It reports p50 / p95 / max and exits non-zero on any failure, so it can
gate a deploy by hand: run it, read three numbers, decide.
"""

import argparse
import asyncio
import sys
import time

import httpx


async def one_request(client: httpx.AsyncClient, url: str, latencies: list, failures: list):
    started = time.perf_counter()
    try:
        response = await client.get(url, timeout=10)
        latencies.append((time.perf_counter() - started) * 1000)
        if response.status_code >= 500:
            failures.append(f"{url} -> {response.status_code}")
    except Exception as error:
        failures.append(f"{url} -> {type(error).__name__}: {error}")


async def main() -> int:
    parser = argparse.ArgumentParser(description="Latency smoke test.")
    parser.add_argument("--url", default="http://localhost:8000")
    parser.add_argument("--requests", type=int, default=50)
    parser.add_argument("--concurrency", type=int, default=10)
    args = parser.parse_args()

    target = f"{args.url.rstrip('/')}/health"
    latencies: list[float] = []
    failures: list[str] = []
    semaphore = asyncio.Semaphore(args.concurrency)

    async with httpx.AsyncClient() as client:
        async def bounded():
            async with semaphore:
                await one_request(client, target, latencies, failures)

        await asyncio.gather(*(bounded() for _ in range(args.requests)))

    if latencies:
        ordered = sorted(latencies)
        p50 = ordered[len(ordered) // 2]
        p95 = ordered[min(len(ordered) - 1, int(len(ordered) * 0.95))]
        print(
            f"{len(latencies)} requests to {target} "
            f"(concurrency {args.concurrency})\n"
            f"p50 {p50:.0f} ms   p95 {p95:.0f} ms   max {ordered[-1]:.0f} ms\n"
            f"(p50 = half of requests were faster than this; "
            f"p95 = 95% were — the number your slowest users feel)"
        )
    if failures:
        print(f"FAILURES ({len(failures)}):")
        for failure in failures[:10]:
            print(f"  {failure}")
        return 1
    print("no failures")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
