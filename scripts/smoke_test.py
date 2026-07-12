#!/usr/bin/env python3
"""Small HTTP smoke test for the backend API. Run manually against a base URL:

    python scripts/smoke_test.py http://localhost:8000
"""
from __future__ import annotations

import sys
import urllib.error
import urllib.request

CHECKS = [
    ('health', '/api/v1/health'),
    ('categories', '/api/v1/categories'),
    ('experience manifest', '/api/v1/experience/manifest'),
]


def main() -> None:
    """Hit each smoke-check route against the given base URL; exit non-zero on any failure."""
    base_url = sys.argv[1].rstrip('/') if len(sys.argv) > 1 else 'http://localhost:8000'
    for name, path in CHECKS:
        try:
            with urllib.request.urlopen(base_url + path, timeout=20) as res:
                print(f'✓ {name}: {res.status}')
        except urllib.error.HTTPError as exc:
            print(f'✗ {name}: HTTP {exc.code}')
            sys.exit(1)
        except Exception as exc:
            print(f'✗ {name}: {exc}')
            sys.exit(1)
    print('All smoke checks passed.')


if __name__ == '__main__':
    main()
