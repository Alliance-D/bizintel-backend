"""
Dependency-light concurrency / latency check for the BizIntel API.

An alternative to Locust when you just want a quick throughput + latency
snapshot without the extra tooling. Fires N concurrent assessment requests in
waves and reports p50/p95/max latency, throughput, and the error rate.

    pip install httpx
    python backend/tests/load/concurrency_check.py --host http://127.0.0.1:8000 \
           --concurrency 25 --requests 500

As with the Locust test, only aim this at the live deployment with permission
and at a modest concurrency: a hard run looks like a small DoS.
"""
import argparse
import asyncio
import random
import statistics
import time

import httpx

POINTS = [
    (-1.9536, 30.0606), (-1.9441, 30.0619), (-1.9706, 30.1044),
    (-1.9339, 30.0587), (-1.9782, 30.1219),
]
CATEGORIES = ["pharmacy", "restaurant", "cafe", "supermarket", "salon"]


async def one_call(client: httpx.AsyncClient) -> tuple[float, int]:
    lat, lng = random.choice(POINTS)
    body = {
        "latitude": lat, "longitude": lng,
        "business_category": random.choice(CATEGORIES), "radius_meters": 500,
    }
    start = time.perf_counter()
    try:
        r = await client.post("/api/v1/platform/assess", json=body, timeout=30.0)
        return (time.perf_counter() - start) * 1000.0, r.status_code
    except Exception:
        return (time.perf_counter() - start) * 1000.0, 0


async def run(host: str, total: int, concurrency: int) -> None:
    limits = httpx.Limits(max_connections=concurrency)
    async with httpx.AsyncClient(base_url=host, limits=limits) as client:
        sem = asyncio.Semaphore(concurrency)

        async def guarded():
            async with sem:
                return await one_call(client)

        wall = time.perf_counter()
        results = await asyncio.gather(*[guarded() for _ in range(total)])
        wall = time.perf_counter() - wall

    lat = sorted(ms for ms, _ in results)
    codes = [c for _, c in results]
    ok = sum(1 for c in codes if 200 <= c < 300)
    limited = sum(1 for c in codes if c == 429)
    errors = sum(1 for c in codes if c == 0 or c >= 500)

    def pct(p):
        return lat[min(len(lat) - 1, int(len(lat) * p))]

    print(f"\nPOST /platform/assess  |  {total} requests @ concurrency {concurrency}")
    print(f"  wall time      : {wall:6.2f} s")
    print(f"  throughput     : {total / wall:6.1f} req/s")
    print(f"  success (2xx)  : {ok}/{total}")
    print(f"  rate-limited   : {limited}  (429; slowapi)")
    print(f"  server errors  : {errors}  (5xx / connection)")
    print(f"  latency p50    : {pct(0.50):7.1f} ms")
    print(f"  latency p95    : {pct(0.95):7.1f} ms")
    print(f"  latency max    : {max(lat):7.1f} ms")
    print(f"  latency mean   : {statistics.mean(lat):7.1f} ms")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="http://127.0.0.1:8000")
    ap.add_argument("--requests", type=int, default=500)
    ap.add_argument("--concurrency", type=int, default=25)
    args = ap.parse_args()
    asyncio.run(run(args.host, args.requests, args.concurrency))
