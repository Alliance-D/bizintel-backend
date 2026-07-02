#!/usr/bin/env python3
from __future__ import annotations

import sys
import urllib.error
import urllib.request

BASE_URL = sys.argv[1].rstrip('/') if len(sys.argv) > 1 else 'http://localhost:8000'
checks = [
    ('health', '/api/v1/health'),
    ('categories', '/api/v1/categories'),
    ('experience manifest', '/api/v1/experience/manifest'),
]

for name, path in checks:
    try:
        with urllib.request.urlopen(BASE_URL + path, timeout=20) as res:
            print(f'✓ {name}: {res.status}')
    except urllib.error.HTTPError as exc:
        print(f'✗ {name}: HTTP {exc.code}')
        sys.exit(1)
    except Exception as exc:
        print(f'✗ {name}: {exc}')
        sys.exit(1)
print('All smoke checks passed.')
