"""
Load / stress test for the BizIntel API (Locust).

Simulates concurrent guest users doing the real things the frontend does:
health checks, category lookups, opportunity-map reads, and point assessments.

Install and run:

    pip install locust

    # interactive UI (open http://localhost:8089), against a local backend:
    locust -f backend/tests/load/locustfile.py --host http://127.0.0.1:8000

    # headless: 50 users, spawn 5/s, run 2 minutes, write a CSV report:
    locust -f backend/tests/load/locustfile.py --host http://127.0.0.1:8000 \
           --headless -u 50 -r 5 -t 2m --csv reports/load

Point --host at the live Render deployment ONLY with permission and at a low
user count: a load test pushed hard is indistinguishable from a small
denial-of-service attack.
"""
from locust import HttpUser, task, between
import random

# Real Kigali coordinates (lat, lng) that fall inside the 500 m analysis grid.
POINTS = [
    (-1.9536, 30.0606),   # Nyarugenge / Kiyovu
    (-1.9441, 30.0619),   # Nyarugenge
    (-1.9706, 30.1044),   # Kicukiro
    (-1.9339, 30.0587),   # Gasabo
    (-1.9782, 30.1219),   # Kicukiro / Kanombe
]
CATEGORIES = ["pharmacy", "restaurant", "cafe", "supermarket", "salon"]


class BizIntelUser(HttpUser):
    # think time between actions, like a real person clicking through the flow
    wait_time = between(1, 4)

    @task(1)
    def health(self):
        self.client.get("/api/v1/health", name="GET /health")

    @task(2)
    def categories(self):
        self.client.get("/api/v1/categories", name="GET /categories")

    @task(3)
    def opportunity_cells(self):
        cat = random.choice(CATEGORIES)
        self.client.get(
            f"/api/v1/platform/opportunity-cells?category={cat}&limit=200",
            name="GET /platform/opportunity-cells",
        )

    @task(5)
    def assess(self):
        lat, lng = random.choice(POINTS)
        cat = random.choice(CATEGORIES)
        with self.client.post(
            "/api/v1/platform/assess",
            json={
                "latitude": lat,
                "longitude": lng,
                "business_category": cat,
                "radius_meters": 500,
            },
            name="POST /platform/assess",
            catch_response=True,
        ) as resp:
            # slowapi rate-limiting returns 429; count it as a handled outcome,
            # not a server error, so the report separates saturation from faults.
            if resp.status_code == 429:
                resp.success()
