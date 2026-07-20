# BizIntel backend

FastAPI + PostgreSQL/PostGIS backend for a business-location intelligence
platform in Kigali. For a given business category it predicts how many
businesses an area's fundamentals (population, income, transport, nearby
anchors) would support, compares that with how many are actually observed
nearby, and reports the **gap** — underserved vs. saturated — using a trained
ML model with a genuine spatial holdout and real SHAP explanations. It is
**not** a business-success, survival, or revenue predictor, and no part of the
product claims otherwise.

## Stack

- **API**: FastAPI, JWT auth (`passlib`/`python-jose`), rate limiting (`slowapi`)
- **Database**: PostgreSQL 16 + PostGIS 3.4, schema versioned with Alembic
- **ML**: scikit-learn, LightGBM, XGBoost, SHAP — see `ml/notebooks/model_development.ipynb`
- **AI Advisor**: Gemini (`google-genai`), optional — degrades gracefully without a key

## Local setup

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate      # macOS/Linux
pip install -r requirements.txt

cp .env.example .env             # then fill in JWT_SECRET, and GEMINI_API_KEY if you want the AI Advisor

# requires a running Postgres/PostGIS instance reachable at DATABASE_URL
alembic upgrade head

uvicorn app.main:app --reload
```

Or via Docker (from the project root, one level up):

```bash
docker compose up --build
```

This builds and starts Postgres/PostGIS, Redis, the API (`:8000`), and the
frontend (`:3000`). Migrations run automatically on container start via
`docker-entrypoint.sh`. For a production-like run:

```bash
JWT_SECRET=... POSTGRES_PASSWORD=... ALLOWED_ORIGINS=... NEXT_PUBLIC_API_BASE_URL=... \
  docker compose -f docker-compose.prod.yml up --build
```

## Deploying to Render

`render.yaml` at the repo root defines a Blueprint: a managed Postgres
database, this backend as a Docker web service, and the
[frontend](https://github.com/Alliance-D/bizintel-frontend) as a native
Node web service (no Docker there, per the frontend's own deploy setup).
From the Render dashboard, New > Blueprint, point it at this repo, and
Render picks up `render.yaml` and provisions all three.

The database and frontend are set to `plan: free`; the backend web service is on
`plan: starter` (a small paid tier) for steadier uptime. Free-tier tradeoffs
worth knowing for the two free services:

- Free web services (here, the frontend) spin down after 15 minutes with no traffic and take
  roughly 30 to 60 seconds to wake back up on the next request, so the
  first request after a quiet period will be slow. Not a bug.
- Free Postgres databases on Render expire 30 days after creation and get
  deleted unless you upgrade the database to a paid plan before then. Real
  data imported for this project (see "Populating real data" below) would
  be lost if the database expires, so treat the free database as
  disposable until you're ready to commit to a paid plan.
- Switching to a paid plan later is a one line change per service, edit
  `plan: free` to `plan: starter` (or another paid tier) for whichever of
  the three needs it, and redeploy the blueprint. No other changes needed.

Before it works end to end:

- Confirm the Render Postgres plan you pick supports the `postgis`
  extension (the migrations run `CREATE EXTENSION IF NOT EXISTS postgis`
  on first boot); if it doesn't, use an external Postgres/PostGIS provider
  and set `DATABASE_URL` manually instead of `fromDatabase`.
- Set `JWT_SECRET` and `GEMINI_API_KEY` in the Render dashboard; they're
  marked `sync: false` in the blueprint so they're not committed.
- The database still starts empty. See "Populating real data" below,
  the import scripts need `DATABASE_URL` pointed at the Render database
  and access to the source datasets, which aren't in this repo.
- `ALLOWED_ORIGINS` and `NEXT_PUBLIC_API_BASE_URL` in `render.yaml` assume
  the default service names (`bizintel-backend`, `bizintel-frontend`);
  update both if you rename either service or attach a custom domain.

## Populating real data

`docker compose up` gives you a working API with an empty database — no
map data or predictions yet. The data pipeline reads from external sources
that are deliberately **not** bundled in this repo (large, and in several
cases restricted microdata that shouldn't be redistributed): boundary
files, an OpenStreetMap extract, and NISR census/survey microdata. See
`scripts/README.md` for the exact pipeline and each script's expected input
path. In short, once you have the source files:

```bash
python scripts/import_admin_boundaries.py ...
python scripts/generate_analysis_grid.py --radius-m 500
python scripts/import_osm_business_features.py --truncate
python scripts/import_population_density.py <path> --truncate
python scripts/import_population_count.py <path> --truncate
python scripts/import_establishment_census.py <path> --truncate
python scripts/import_population_welfare.py <path> --truncate
python scripts/import_district_socioeconomic.py --lfs <path> --vup <path> --truncate
python scripts/build_grid_category_features.py --truncate
python scripts/train_and_score_opportunity_model.py --activate
```

The last two steps (and retraining afterward) can also be triggered from
the admin API once the server is running: `POST /api/v1/admin/jobs/rebuild-features`
and `POST /api/v1/admin/jobs/retrain` (admin role required).

## Model

The opportunity map is driven by a **two-part (hurdle) model** that predicts,
for each 500 m grid cell and business category, how many businesses of that
category the area's *fundamentals* would support, then compares that to how many
are actually observed. The gap (expected − observed) is the finding; cells are
banded by their gap percentile within category (Underserved / Room to grow /
Balanced / Saturated).

- **Trains on** `ml.grid_category_features` (~5,655 cell × category rows). Inputs
  are leak-free area fundamentals only — population, income, welfare, POIs,
  transport, road/intersection density, per-anchor distances. The category's own
  current presence is **excluded** from the inputs; it *is* the target.
- **Target** `observed_count` — same-category businesses within 1 km (OSM-derived).
- **Stage 1 — presence:** ExtraTrees classifier, `P(any present)` → the
  **viability** signal. **Stage 2 — count:** ExtraTrees regressor on a `log1p`
  target, fit only on present cells. Expected = `P(present) × E(count | present)`.
- **Validation** is honest: repeated **grouped spatial cross-validation**
  (held-out sectors), not a single random split.

Held-out performance of the live model:

| metric | value |
|---|---|
| combined MAE | **0.508** |
| combined R² | **0.595** |
| presence AUC | **0.965** |
| count-stage MAE (present cells) | ~2.45 (≈30% better than a no-feature baseline) |
| gap-ranking stability (Spearman) | 0.786 |
| underserved-set overlap across variants | 89.4% |
| viability stability (Spearman) | 0.876 |

The count target is fat-tailed (median 2, max 41), so the exact count is a rough
estimate — the robust, defensible outputs are the **band** and the **viability
probability**. What moved the numbers was **log-transforming the count target and
dropping the non-generalising `sector` one-hot** (it can't transfer to unseen
sectors) while keeping rich trees — over-regularising only made held-out error
worse. The full comparison, learning curves, SHAP and a robustness/sensitivity
check live in `ml/notebooks/model_development.ipynb` and
`scripts/robustness_check.py`.

## Data sources and governance

Real Rwanda data, not synthetic placeholders — see `docs/CHANGELOG.md` at
the project root for the full history:

| Source | Resolution | Used for |
|---|---|---|
| NISR administrative boundaries | sector/cell/village | grid geometry, area lookups |
| WorldPop population density | ~1km raster | demand features |
| NISR population count | sector | demand features |
| OpenStreetMap (Kigali extract) | point | competitor/POI counts, accessibility |
| NISR Establishment Census 2023 | district | commercial-density features |
| NISR PHC5 census 2022 | sector | demographic/welfare features |
| NISR Labour Force Survey 2025 | district | employment-rate features |
| VUP welfare survey | district | poverty-rate features |

Raw microdata is never committed or exposed through the API — only
aggregated, non-identifying counts (see `.gitignore` and each
`scripts/import_*.py`'s docstring for exactly what's aggregated and how).
`meta.feature_catalog` documents every feature's source, calculation, and
known limitations for the product's methodology/transparency surface.

## Tests

```bash
pytest
```

## Project layout

```
app/
  api/routes/    FastAPI routers, one file per resource
  core/          config, JWT/RBAC, rate limiting, middleware
  data/          dataset catalog service
  db/            session, schema.py (the canonical schema), bootstrap check
  geo/           shared spatial dataclasses
  ml/            model registry (artifact loading, version metadata)
  schemas/       Pydantic request/response models
  services/      business logic, one file per domain
alembic/         schema migrations (schema.py's CANONICAL_SCHEMA_SQL is the baseline)
ml/
  artifacts/     trained model artifacts (gitignored, regenerated by training)
  notebooks/     ML development notebook
scripts/         data import + ML pipeline, run manually or via the admin API
tests/           pytest suite (tests/load/ holds Locust + concurrency load tests)
```

## Known limitations

- The Establishment Census has no sector/GPS field, so `pharmacy`/`grocery`
  and `restaurant`/`cafe` currently share one 1-digit ISIC industry bucket
  each and get identical district-level establishment-density signal.
- PHC5 is a 2022 snapshot; fast-growing sectors may have shifted since.
- OSM competitor counts miss informal/unmapped businesses — every product
  surface recommends a field visit before committing to a location.
- Field validation (`field.validation_points`) is designed as a calibration
  check against the model's predictions, not additional training data —
  see the notebook's field-validation section.
