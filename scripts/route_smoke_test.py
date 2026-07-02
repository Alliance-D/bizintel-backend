"""Small HTTP smoke test for the backend API."""
import argparse
import json
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError

ROUTES = [
    "/api/v1/health",
    "/api/v1/categories",
    "/api/v1/readiness",
]


def fetch(url: str) -> tuple[int, str]:
    req = Request(url, headers={"Accept": "application/json"})
    with urlopen(req, timeout=15) as res:
        return res.status, res.read().decode("utf-8")[:500]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://localhost:8000")
    args = parser.parse_args()
    results = []
    ok = True
    for route in ROUTES:
        url = args.base_url.rstrip("/") + route
        try:
            status, body = fetch(url)
            results.append({"route": route, "status": status, "ok": 200 <= status < 300, "sample": body})
            ok = ok and 200 <= status < 300
        except (URLError, HTTPError, TimeoutError) as exc:
            results.append({"route": route, "status": None, "ok": False, "error": str(exc)})
            ok = False
    print(json.dumps(results, indent=2))
    if not ok:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
