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
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.categories import normalise_category
from app.services.ai_advisor_service import generate_advice
from app.services.geography_service import get_village_boundary
from app.services.ml_opportunity_service import assess_location_ml, list_nearby_competitors
from app.services.opportunity_service import list_opportunity_cells


def _user_context(payload: dict[str, Any]) -> dict[str, str] | None:
    budget = payload.get("budget")
    notes = payload.get("notes")
    return {"budget": budget, "notes": notes} if (budget or notes) else None


def build_point_entry(db: Session, category: str, point: dict[str, Any], locale: str | None, user_context: dict[str, str] | None) -> dict[str, Any]:
    latitude = float(point["latitude"])
    longitude = float(point["longitude"])
    assessment = assess_location_ml(db, latitude, longitude, category, 500, locale=locale)
    competitors = list_nearby_competitors(db, latitude, longitude, category)
    boundary = get_village_boundary(db, latitude, longitude)
    narrative = generate_advice(assessment, locale=locale, user_context=user_context)
    return {
        "mode": "point",
        "label": point.get("label") or assessment.get("location_label"),
        "latitude": latitude,
        "longitude": longitude,
        "assessment": assessment,
        "competitors": competitors,
        "village_boundary": boundary,
        "narrative": narrative,
    }


def build_area_entry(db: Session, category: str, area: dict[str, Any], locale: str | None) -> dict[str, Any]:
    district = area["district"]
    sector = area.get("sector")
    cell = area.get("cell")
    candidates = list_opportunity_cells(db, category=category, district=district, sector=sector, cell=cell, limit=3, locale=locale)
    return {
        "mode": "area",
        "label": area.get("label") or cell or sector or district,
        "district": district,
        "sector": sector,
        "cell": cell,
        "top_candidates": candidates,
    }


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
        gap_score = overall.get("gap_score", overall.get("opportunity_score", 0))
        results.append({
            "label": e.get("label") or assessment.get("location_label"),
            "latitude": e["latitude"],
            "longitude": e["longitude"],
            "district": assessment.get("district"),
            "sector": assessment.get("sector"),
            "cell": assessment.get("cell"),
            "village": assessment.get("village"),
            "location_label": assessment.get("location_label"),
            "gap_score": gap_score,
            "opportunity_score": gap_score,
            "opportunity_type": overall.get("opportunity_type"),
            "confidence_score": overall.get("confidence_score"),
            "expected_count": overall.get("expected_count"),
            "observed_count": overall.get("observed_count"),
            "gap": overall.get("gap"),
            "demand_score": factors.get("demand_score"),
            "accessibility_score": factors.get("accessibility_score"),
            "commercial_activity_score": factors.get("commercial_activity_score"),
            "competition_pressure": factors.get("competition_pressure"),
            "recommendation": assessment.get("recommendation"),
        })
    results.sort(key=lambda r: r["gap_score"], reverse=True)
    winner = results[0]
    summary = (
        f"{winner['label']} ni ho hafite icyuho kinini hagati y'ubukenewe n'ibiboneka ku {business_category.replace('_', ' ')}, ni ho hakiri umwanya munini."
        if rw else
        f"{winner['label']} shows the largest demand-versus-supply gap for {business_category.replace('_', ' ')} - the most underserved of the options compared."
    )
    return {"locations": results, "best_location": winner, "summary": summary}


def build_unified_report(db: Session, payload: dict[str, Any]) -> dict[str, Any]:
    category = normalise_category(payload["business_category"])
    locale = payload.get("locale")
    user_context = _user_context(payload)

    entries = [
        build_area_entry(db, category, loc, locale) if loc.get("mode") == "area"
        else build_point_entry(db, category, loc, locale, user_context)
        for loc in payload["locations"]
    ]
    point_entries = [e for e in entries if e["mode"] == "point"]
    comparison = build_comparison_from_entries(point_entries, category, locale)

    return {
        "business_category": category,
        "budget": payload.get("budget"),
        "notes": payload.get("notes"),
        "locale": locale,
        "entries": entries,
        "comparison": comparison,
    }


def _synthesize_title(report: dict[str, Any]) -> str:
    category = report["business_category"].replace("_", " ").title()
    entries = report["entries"]
    if len(entries) == 1:
        return f"{category} report - {entries[0].get('label') or 'Kigali'}"
    return f"{category} report - {len(entries)} locations"


def persist_unified_report(db: Session, report: dict[str, Any]) -> int | None:
    try:
        first_point = next((e for e in report["entries"] if e["mode"] == "point"), None)
        row = db.execute(text("""
            INSERT INTO app.location_reports (title, business_category, latitude, longitude, report_payload, status)
            VALUES (:title, :category, :lat, :lon, CAST(:payload AS JSONB), 'ready')
            RETURNING id
        """), {
            "title": _synthesize_title(report),
            "category": report["business_category"],
            "lat": first_point["latitude"] if first_point else None,
            "lon": first_point["longitude"] if first_point else None,
            "payload": json.dumps(report),
        }).first()
        db.commit()
        return int(row[0]) if row else None
    except Exception:
        db.rollback()
        return None


def get_unified_report(db: Session, report_id: int) -> dict[str, Any] | None:
    try:
        row = db.execute(text("SELECT report_payload FROM app.location_reports WHERE id = :id"), {"id": report_id}).first()
        return row[0] if row else None
    except Exception:
        db.rollback()
        return None


def expand_candidate(db: Session, report_id: int, entry_index: int, grid_id: str, latitude: float, longitude: float, label: str | None) -> dict[str, Any] | None:
    report = get_unified_report(db, report_id)
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
        db.execute(text("UPDATE app.location_reports SET report_payload = CAST(:payload AS JSONB) WHERE id = :id"), {"payload": json.dumps(report), "id": report_id})
        db.commit()
    except Exception:
        db.rollback()
        return None
    return point_entry
