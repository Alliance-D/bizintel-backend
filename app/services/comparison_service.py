from __future__ import annotations

from sqlalchemy.orm import Session

from app.services.ml_opportunity_service import assess_location_ml


def compare_locations(db: Session, business_category: str, locations: list[dict], locale: str | None = None) -> dict:
    rw = (locale or "").lower().startswith(("rw", "kin"))
    results = []
    for item in locations:
        assessment = assess_location_ml(db, item["latitude"], item["longitude"], business_category, item.get("radius_meters", 500), locale=locale)
        overall = assessment.get("overall", {})
        gap_score = overall.get("gap_score", overall.get("opportunity_score", 0))
        factors = assessment.get("factors", {})
        default_label = item.get("label") or assessment.get("location_label") or (f"Ahantu {len(results)+1}" if rw else f"Location {len(results)+1}")
        results.append({
            "label": default_label,
            "latitude": item["latitude"],
            "longitude": item["longitude"],
            "district": assessment.get("district"),
            "sector": assessment.get("sector"),
            "cell": assessment.get("cell"),
            "village": assessment.get("village"),
            "location_label": assessment.get("location_label"),
            "gap_score": gap_score,
            "opportunity_score": gap_score,  # kept for callers not yet migrated to gap_score
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
    winner = results[0] if results else None
    if winner:
        summary = f"{winner['label']} ni ho hafite icyuho kinini hagati y'ubukenewe n'ibiboneka ku {business_category.replace('_', ' ')}, ni ho hakiri umwanya munini." if rw \
            else f"{winner['label']} shows the largest demand-versus-supply gap for {business_category.replace('_', ' ')} - the most underserved of the options compared."
    else:
        summary = "Ongeraho ahantu kugira ngo ugereranye." if rw else "Add locations to compare."
    return {
        "business_category": business_category,
        "locations": results,
        "best_location": winner,
        "summary": summary,
    }
