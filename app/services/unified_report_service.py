"""Builds the single unified results/report bundle behind the /start form ->
/report/[id] flow: one or more locations (exact points or broad areas),
scored with the real ML gap model, explained by Gemini, and persisted as one
JSONB blob so the report is a real, shareable, refresh-safe URL.

Efficiency note: Gemini narration is generated immediately for submitted
exact points, but deferred for an area's top-3 ranked candidates until the
user actually expands one (expand_candidate) - an area search would
otherwise burn 3x the Gemini calls for candidates nobody looks at.
"""
from __future__ import annotations

import json
import secrets
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

# Reports are shared by URL with no per-user auth, so they are addressed by a
# random token (not the sequential id) and pruned after a retention window so
# the table doesn't grow without bound.
REPORT_RETENTION_DAYS = 30

from app.core.categories import normalise_category
from app.services.ai_advisor_service import generate_advice
from app.services.geography_service import get_village_boundary
from app.services.ml_opportunity_service import assess_location_ml, list_nearby_competitors, list_nearby_pois
from app.services.opportunity_service import list_opportunity_cells

# Foot-traffic generators - the POIs that pull a stream of people past a
# storefront (bus stops, markets, schools, clinics).
ANCHOR_CATEGORIES = ["transport", "market", "school", "health"]
# Businesses that draw a similar customer to the target category.
BUSINESS_CATEGORIES = ["pharmacy", "restaurant", "cafe", "grocery", "salon", "finance", "commercial_support"]


def _user_context(payload: dict[str, Any]) -> dict[str, str] | None:
    """Extract optional user-stated budget/notes context from the request payload."""
    budget = payload.get("budget")
    notes = payload.get("notes")
    return {"budget": budget, "notes": notes} if (budget or notes) else None


def build_point_entry(db: Session, category: str, point: dict[str, Any], locale: str | None, user_context: dict[str, str] | None) -> dict[str, Any]:
    """Build a full report entry for one exact coordinate."""
    latitude = float(point["latitude"])
    longitude = float(point["longitude"])
    assessment = assess_location_ml(db, latitude, longitude, category, 500, locale=locale)
    competitors = list_nearby_competitors(db, latitude, longitude, category)
    anchors = list_nearby_pois(db, latitude, longitude, ANCHOR_CATEGORIES, radius_meters=1000, limit=30)
    complementary = list_nearby_pois(db, latitude, longitude, [c for c in BUSINESS_CATEGORIES if c != category], radius_meters=1000, limit=30)
    boundary = get_village_boundary(db, latitude, longitude)
    narrative = generate_advice(assessment, locale=locale, user_context=user_context)
    return {
        "mode": "point",
        "label": point.get("label") or assessment.get("location_label"),
        "latitude": latitude,
        "longitude": longitude,
        "assessment": assessment,
        "competitors": competitors,
        "anchors": anchors,
        "complementary": complementary,
        "village_boundary": boundary,
        "narrative": narrative,
    }


def build_area_entry(db: Session, category: str, area: dict[str, Any], locale: str | None) -> dict[str, Any]:
    """Build an area entry: the ranked shortlist of the strongest cells in an area."""
    district = area["district"]
    sector = area.get("sector")
    cell = area.get("cell")
    candidates = list_opportunity_cells(db, category=category, district=district, sector=sector, cell=cell, limit=3, locale=locale, with_landmarks=True)
    return {
        "mode": "area",
        "label": area.get("label") or cell or sector or district,
        "district": district,
        "sector": sector,
        "cell": cell,
        "top_candidates": candidates,
    }


def _best_spot_entry(db: Session, category: str, loc: dict[str, Any], locale: str | None, user_context: dict[str, str] | None) -> dict[str, Any] | None:
    """Resolve one form location to a single concrete spot as a full point entry,
    for head-to-head comparison. A point is itself; an area collapses to its
    top-ranked grid cell (the spot we'd actually recommend inside it)."""
    if loc.get("mode") == "area":
        cands = list_opportunity_cells(
            db, category=category, district=loc["district"], sector=loc.get("sector"),
            cell=loc.get("cell"), limit=1, locale=locale, with_landmarks=True,
        )
        if not cands:
            return None
        c = cands[0]
        point = {"latitude": c["latitude"], "longitude": c["longitude"], "label": loc.get("label") or c.get("landmark") or c.get("location_label")}
        entry = build_point_entry(db, category, point, locale, user_context)
        entry["area_scope"] = {"district": loc["district"], "sector": loc.get("sector"), "cell": loc.get("cell")}
        return entry
    return build_point_entry(db, category, loc, locale, user_context)


def build_comparison_from_entries(point_entries: list[dict[str, Any]], business_category: str, locale: str | None) -> dict[str, Any] | None:
    """Same shape as comparison_service.compare_locations()'s output, but built
    from assessments already computed in build_point_entry - avoids a second,
    redundant assess_location_ml() round trip per location."""
    if len(point_entries) < 2:
        return None
    rw = (locale or "").lower().startswith(("rw", "kin"))
    results = []
    for e in point_entries:
        assessment = e["assessment"]
        overall = assessment.get("overall", {})
        factors = assessment.get("factors", {})
        signals = assessment.get("signals") or {}
        gap_score = overall.get("gap_score", overall.get("opportunity_score", 0))
        results.append({
            "label": e.get("label") or assessment.get("landmark") or assessment.get("location_label"),
            "landmark": assessment.get("landmark"),
            "latitude": e["latitude"],
            "longitude": e["longitude"],
            "district": assessment.get("district"),
            "sector": assessment.get("sector"),
            "cell": assessment.get("cell"),
            "location_label": assessment.get("location_label"),
            "gap_score": gap_score,
            "opportunity_score": gap_score,
            "opportunity_type": overall.get("opportunity_type"),
            "confidence_score": overall.get("confidence_score"),
            "expected_count": overall.get("expected_count"),
            "observed_count": overall.get("observed_count"),
            "gap": overall.get("gap"),
            "people_within_1km": signals.get("people_within_1km"),
            "anchor_count": signals.get("anchor_count_1000m"),
            "demand_score": factors.get("demand_score"),
            "accessibility_score": factors.get("accessibility_score"),
            "commercial_activity_score": factors.get("commercial_activity_score"),
            "competition_pressure": factors.get("competition_pressure"),
            "recommendation": assessment.get("recommendation"),
        })
    results.sort(key=lambda r: (r["gap_score"], -(r.get("competition_pressure") or 0)), reverse=True)
    winner, runner = results[0], results[1]
    summary = _comparison_summary(winner, runner, business_category, rw)
    return {"locations": results, "best_location": winner, "summary": summary}


def _num(v: Any) -> float:
    """Coerce a value to float, defaulting to 0.0."""
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _comparison_summary(winner: dict[str, Any], runner: dict[str, Any], category: str, rw: bool) -> str:
    """A plain-language reason the winner edges the runner-up, in terms a founder
    cares about: room to grow, competition, and the customer base."""
    cat = category.replace("_", " ")
    w_room = _num(winner.get("expected_count")) - _num(winner.get("observed_count"))
    r_room = _num(runner.get("expected_count")) - _num(runner.get("observed_count"))
    reasons_en, reasons_rw = [], []
    if w_room - r_room >= 0.5:
        reasons_en.append("more unmet demand")
        reasons_rw.append("ubukene butarakemuka bwinshi")
    if _num(runner.get("observed_count")) - _num(winner.get("observed_count")) >= 1:
        reasons_en.append("fewer competitors already there")
        reasons_rw.append("abahatanwa bake bahasanzwe")
    if _num(winner.get("people_within_1km")) - _num(runner.get("people_within_1km")) >= 1500:
        reasons_en.append("a larger customer base nearby")
        reasons_rw.append("abakiriya benshi bo hafi")
    if rw:
        why = (", ".join(reasons_rw[:2]) or "icyuho kinini hagati y'ubukenewe n'ibiboneka")
        return f"{winner['label']} ni ho hakwiye kubanza ku {cat}: gafite {why} ugereranyije na {runner['label']}."
    why = (", and ".join(reasons_en[:2]) or "a wider gap between demand and what's already open")
    return f"{winner['label']} is the stronger pick for a {cat}: it has {why} compared with {runner['label']}."


def build_unified_report(db: Session, payload: dict[str, Any]) -> dict[str, Any]:
    """Build the unified report: compare mode for two or more locations, else single/area."""
    category = normalise_category(payload["business_category"])
    locale = payload.get("locale")
    user_context = _user_context(payload)
    locations = payload["locations"]

    if len(locations) >= 2:
        # Comparison: resolve every location to a single concrete spot (an area
        # collapses to its best cell) and put them head-to-head, rather than
        # showing each area's own internal shortlist side by side.
        entries = [e for e in (_best_spot_entry(db, category, loc, locale, user_context) for loc in locations) if e is not None]
        comparison = build_comparison_from_entries(entries, category, locale)
        report_mode = "compare"
    else:
        loc = locations[0]
        entries = [
            build_area_entry(db, category, loc, locale) if loc.get("mode") == "area"
            else build_point_entry(db, category, loc, locale, user_context)
        ]
        comparison = None
        report_mode = "single"

    return {
        "business_category": category,
        "budget": payload.get("budget"),
        "notes": payload.get("notes"),
        "locale": locale,
        "mode": report_mode,
        "entries": entries,
        "comparison": comparison,
    }


def _synthesize_title(report: dict[str, Any]) -> str:
    """Derive a human-readable title for a report from its entries."""
    category = report["business_category"].replace("_", " ").title()
    entries = report["entries"]
    if len(entries) == 1:
        return f"{category} report - {entries[0].get('label') or 'Kigali'}"
    return f"{category} report - {len(entries)} locations"


def _purge_expired_reports(db: Session) -> None:
    """Delete reports past the retention window. Best-effort and self-contained
    (its own transaction) so a purge failure never blocks saving a new report."""
    try:
        db.execute(
            text("DELETE FROM app.location_reports WHERE created_at < now() - make_interval(days => :days)"),
            {"days": REPORT_RETENTION_DAYS},
        )
        db.commit()
    except Exception:
        db.rollback()


def persist_unified_report(db: Session, report: dict[str, Any]) -> str | None:
    """Persist a unified report and return its non-guessable public token."""
    _purge_expired_reports(db)
    try:
        first_point = next((e for e in report["entries"] if e["mode"] == "point"), None)
        token = secrets.token_urlsafe(9)
        row = db.execute(text("""
            INSERT INTO app.location_reports (public_token, title, business_category, latitude, longitude, report_payload, status)
            VALUES (:token, :title, :category, :lat, :lon, CAST(:payload AS JSONB), 'ready')
            RETURNING public_token
        """), {
            "token": token,
            "title": _synthesize_title(report),
            "category": report["business_category"],
            "lat": first_point["latitude"] if first_point else None,
            "lon": first_point["longitude"] if first_point else None,
            "payload": json.dumps(report),
        }).first()
        db.commit()
        return str(row[0]) if row else None
    except Exception:
        db.rollback()
        return None


def get_unified_report(db: Session, report_token: str) -> dict[str, Any] | None:
    """Fetch a persisted unified report by its public token."""
    try:
        row = db.execute(text("SELECT report_payload FROM app.location_reports WHERE public_token = :token"), {"token": report_token}).first()
        return row[0] if row else None
    except Exception:
        db.rollback()
        return None


def expand_candidate(db: Session, report_token: str, entry_index: int, grid_id: str, latitude: float, longitude: float, label: str | None) -> dict[str, Any] | None:
    """Expand one area candidate cell into its own full point report."""
    report = get_unified_report(db, report_token)
    if report is None or entry_index < 0 or entry_index >= len(report["entries"]):
        return None
    entry = report["entries"][entry_index]
    if entry.get("mode") != "area":
        return None

    category = report["business_category"]
    locale = report.get("locale")
    user_context = _user_context(report)
    point_entry = build_point_entry(db, category, {"latitude": latitude, "longitude": longitude, "label": label}, locale, user_context)
    entry["expanded_candidate"] = point_entry

    try:
        db.execute(text("UPDATE app.location_reports SET report_payload = CAST(:payload AS JSONB) WHERE public_token = :token"), {"payload": json.dumps(report), "token": report_token})
        db.commit()
    except Exception:
        db.rollback()
        return None
    return point_entry
