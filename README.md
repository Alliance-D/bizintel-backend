# BizIntel backend

FastAPI + PostgreSQL/PostGIS backend for **BizIntel** — a spatial
business-location intelligence platform for Kigali. For a business category it
predicts how many businesses an area's fundamentals (population, income,
transport, nearby anchors) would support, compares that with how many are
actually observed nearby, and reports the **gap** — under-served vs. saturated —
from a trained, spatially-validated ML model with real SHAP explanations. It is
**not** a business-success, survival, or revenue predictor.

## 📖 Full documentation

The complete project documentation — overview, full setup, the data pipeline and
sources, the ML model, deployment, and the verification runbook — is consolidated
into the **main project README** (in the frontend repository):

**→ https://github.com/Alliance-D/bizintel-frontend#readme**

## Quick start

```bash
python -m venv .venv
.venv\Scripts\activate            # Windows  (source .venv/bin/activate on macOS/Linux)
pip install -r requirements.txt
cp .env.example .env               # set JWT_SECRET (and GEMINI_API_KEY for the AI advisor)
alembic upgrade head               # create the schema (needs Postgres/PostGIS at DATABASE_URL)
uvicorn app.main:app --reload      # http://localhost:8000  (interactive docs at /docs)
pytest                             # run the tests
```

Requires **Python 3.13** and **PostgreSQL 16 + PostGIS 3.4**. The database starts
empty — see the main README for the data pipeline and how to populate it, or run
the whole stack (database included) with `docker compose up --build` from the
parent folder.

## Links

- Main documentation / frontend repo: https://github.com/Alliance-D/bizintel-frontend
- Live app: https://bizintel-frontend.onrender.com/
- Live API: https://bizintel-backend-atgv.onrender.com (docs at `/docs`)
