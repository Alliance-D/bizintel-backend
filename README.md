# BizIntel backend

FastAPI + PostgreSQL/PostGIS backend for a business-location intelligence
platform in Kigali. It scores candidate locations on a transparent
demand/accessibility/commercial-activity/competition/welfare composite,
refined by a trained ML model with a genuine spatial holdout and real SHAP
explanations — it is **not** a business-success, survival, or revenue
predictor, and no part of the product claims otherwise.

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
tests/           pytest suite
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
