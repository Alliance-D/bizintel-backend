import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.core.config import get_settings
from app.core.middleware import RequestContextMiddleware, SecurityHeadersMiddleware
from app.db.session import engine
from app.api.routes import health, categories, opportunity, competitive, insights, admin, datasets, features, models, compare, reports, watchlists, auth, field_validation, tiles, notifications, live_layers, ml_opportunity, experience, workbench, security, readiness, platform, i18n, tutorial

logger = logging.getLogger(__name__)

settings = get_settings()

app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    description="ML-based spatial business opportunity intelligence API.",
)

app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(RequestContextMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def root() -> dict:
    return {
        "name": settings.app_name,
        "status": "running",
        "docs": "/docs",
        "health": "/api/v1/health",
    }


@app.on_event("startup")
def startup() -> None:
    """Verify the schema is migrated; does not create it. Run `alembic upgrade head` first."""
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1 FROM ml.grid_category_features LIMIT 1"))
    except SQLAlchemyError:
        logger.error(
            "Database schema is missing or out of date. Run 'alembic upgrade head' "
            "before starting the API."
        )
        raise


app.include_router(health.router, prefix="/api/v1", tags=["health"])
app.include_router(categories.router, prefix="/api/v1", tags=["categories"])
app.include_router(i18n.router, prefix="/api/v1", tags=["i18n"])
app.include_router(tutorial.router, prefix="/api/v1", tags=["tutorial"])
app.include_router(opportunity.router, prefix="/api/v1/opportunity", tags=["opportunity"])
app.include_router(competitive.router, prefix="/api/v1/competitive", tags=["competitive"])
app.include_router(insights.router, prefix="/api/v1/insights", tags=["insights"])
app.include_router(datasets.router, prefix="/api/v1", tags=["datasets"])
app.include_router(features.router, prefix="/api/v1", tags=["features"])
app.include_router(models.router, prefix="/api/v1", tags=["models"])
app.include_router(compare.router, prefix="/api/v1/compare", tags=["compare"])
app.include_router(reports.router, prefix="/api/v1/reports", tags=["reports"])
app.include_router(watchlists.router, prefix="/api/v1", tags=["watchlists"])
app.include_router(auth.router, prefix="/api/v1/auth", tags=["auth"])
app.include_router(field_validation.router, prefix="/api/v1/field-validation", tags=["field-validation"])
app.include_router(tiles.router, prefix="/api/v1/tiles", tags=["tiles"])
app.include_router(notifications.router, prefix="/api/v1", tags=["notifications"])
app.include_router(live_layers.router, prefix="/api/v1/live", tags=["live-layers"])
app.include_router(ml_opportunity.router, prefix="/api/v1/ml-opportunity", tags=["ml-opportunity"])
app.include_router(experience.router, prefix="/api/v1/experience", tags=["experience"])
app.include_router(platform.router, prefix="/api/v1/platform", tags=["platform"])
app.include_router(workbench.router, prefix="/api/v1/workbench", tags=["workbench"])
app.include_router(security.router, prefix="/api/v1/admin/security", tags=["security"])
app.include_router(readiness.router, prefix="/api/v1/readiness", tags=["readiness"])
app.include_router(admin.router, prefix="/api/v1/admin", tags=["admin"])
