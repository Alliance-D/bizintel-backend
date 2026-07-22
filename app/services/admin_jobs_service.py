"""Long-running admin operations (retraining, model activation) run as a
background subprocess rather than blocking a request. This is intentionally
simple - a single-worker lock and a log file - rather than a full job queue
(Celery/RQ), which isn't justified at this project's scale yet. Swapping in a
real queue later would replace this module without touching its callers.
"""
from __future__ import annotations

import subprocess
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

_lock = threading.Lock()
_state: dict[str, Any] = {"running": False, "job_name": None, "started_at": None, "finished_at": None, "exit_code": None, "log_path": None}

LOG_DIR = Path("ml/artifacts/job_logs")


def job_status() -> dict[str, Any]:
    """Return the status of the current or most recent background job."""
    with _lock:
        return dict(_state)


def _run(job_name: str, command: list[str], log_path: Path) -> None:
    """Run a job subprocess, streaming its output to a log file and updating job state."""
    with log_path.open("w", encoding="utf-8") as log_file:
        process = subprocess.run(command, stdout=log_file, stderr=subprocess.STDOUT)
    with _lock:
        _state.update(running=False, finished_at=datetime.now(timezone.utc).isoformat(), exit_code=process.returncode)


def _start_background_job(job_name: str, command: list[str]) -> dict[str, Any]:
    """Start a background job thread unless one is already running."""
    with _lock:
        if _state["running"]:
            return {"started": False, "message": f"A job ({_state['job_name']}) is already running.", "status": dict(_state)}
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        log_path = LOG_DIR / f"{job_name}_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.log"
        _state.update(running=True, job_name=job_name, started_at=datetime.now(timezone.utc).isoformat(), finished_at=None, exit_code=None, log_path=str(log_path))

    thread = threading.Thread(target=_run, args=(job_name, command, log_path), daemon=True)
    thread.start()
    return {"started": True, "message": f"{job_name} started in the background.", "status": job_status()}


def trigger_retrain(activate: bool = True) -> dict[str, Any]:
    """Start the model retrain-and-score job."""
    command = [sys.executable, "scripts/train_and_score_opportunity_model.py"]
    if activate:
        command.append("--activate")
    return _start_background_job("retrain_opportunity_model", command)


def trigger_grid_rebuild() -> dict[str, Any]:
    """Start the grid feature-rebuild job."""
    command = [sys.executable, "scripts/build_grid_category_features.py", "--truncate"]
    return _start_background_job("rebuild_grid_features", command)


def activate_model_version(db: Session, model_version_id: int) -> dict[str, Any]:
    """Switch which already-trained model is live, without retraining.

    Only meaningful for a version that still has scored predictions - old
    versions have theirs deleted on deactivation (see migration 0002) to
    keep ml.ml_opportunity_predictions scoped to one live model at a time.
    Activating a version with no predictions would make location lookups
    silently return nothing, so that case is refused rather than allowed.
    """
    target = db.execute(text("SELECT id, target_name FROM ml.model_versions WHERE id = :id"), {"id": model_version_id}).mappings().first()
    if not target:
        return {"activated": False, "message": f"No model version with id {model_version_id}."}

    prediction_count = db.execute(text(
        "SELECT COUNT(*) FROM ml.ml_opportunity_predictions WHERE model_version_id = :id"
    ), {"id": model_version_id}).scalar_one()
    if prediction_count == 0:
        return {
            "activated": False,
            "message": (
                f"Model version {model_version_id} has no scored predictions (they were cleared "
                "when it was deactivated). Retrain it instead of activating it directly - "
                "retraining scores every grid cell against the resulting model."
            ),
        }

    with db.begin():
        db.execute(text("UPDATE ml.model_versions SET is_active = FALSE, activated_at = NULL WHERE target_name = :target AND business_category IS NULL"), {"target": target["target_name"]})
        db.execute(text("UPDATE ml.model_versions SET is_active = TRUE, activated_at = now() WHERE id = :id"), {"id": model_version_id})
    return {"activated": True, "message": f"Model version {model_version_id} is now active ({prediction_count:,} predictions)."}
