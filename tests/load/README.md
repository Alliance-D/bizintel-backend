# Load / stress tests

These exercise the API under concurrency, which the functional and end-to-end
suites do not. They are kept out of the default `pytest` run because they need a
running backend and are meant to be pointed at a target deliberately.

| File | What it does | Needs |
|------|--------------|-------|
| `locustfile.py` | Simulates concurrent guest users (health, categories, opportunity-map, assess) with think time; interactive UI or headless CSV report | `pip install locust` |
| `concurrency_check.py` | Fires N concurrent `/assess` requests and prints throughput + p50/p95/max latency + error rate | `pip install httpx` |

## Run against a local backend

```bash
# start the backend first (needs PostgreSQL + PostGIS), then:
locust -f backend/tests/load/locustfile.py --host http://127.0.0.1:8000 \
       --headless -u 50 -r 5 -t 2m --csv reports/load

python backend/tests/load/concurrency_check.py --host http://127.0.0.1:8000 \
       --concurrency 25 --requests 500
```

## Caution

Only point `--host` at the live Render deployment with permission and at a low
user count. A load test pushed hard is indistinguishable from a small
denial-of-service attack, and slowapi rate-limiting (HTTP 429) will kick in.
The scripts count 429 as a handled outcome so the report separates *saturation*
(rate-limited) from *faults* (5xx / connection errors).
