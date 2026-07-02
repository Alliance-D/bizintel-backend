from sqlalchemy import text
from sqlalchemy.orm import Session


def get_readiness(db: Session) -> dict:
    """Return launch readiness summary and demo scenarios.

    This service intentionally degrades gracefully when Phase 10 SQL has not
    been applied yet, so the API can still support early demos.
    """
    try:
        summary_rows = db.execute(text("SELECT * FROM app.v_release_readiness")).mappings().all()
    except Exception:
        summary_rows = []

    try:
        scenario_rows = db.execute(text("SELECT * FROM app.v_demo_scenarios LIMIT 20")).mappings().all()
    except Exception:
        scenario_rows = []

    total_open = sum(int(row.get("open_items", 0)) for row in summary_rows)
    status = "ready" if summary_rows and total_open == 0 else "needs_attention"

    next_actions = [
        "Run SQL migrations through backend/sql/014_demo_seed_and_final_views.sql.",
        "Import and verify curated spatial layers before using live opportunity scoring.",
        "Generate the training matrix and register an active ML model before public demo.",
        "Run smoke tests against backend and frontend deployment URLs.",
    ]

    return {
        "status": status,
        "summary": [dict(row) for row in summary_rows],
        "demo_scenarios": [dict(row) for row in scenario_rows],
        "next_actions": next_actions,
    }
