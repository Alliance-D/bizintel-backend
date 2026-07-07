from __future__ import annotations

from sqlalchemy.orm import Session

from app.services.ml_opportunity_service import assess_location_ml


def compare_locations(db: Session, business_category: str, locations: list[dict], locale: str | None = None) -> dict:
    rw = (locale or "").lower().startswith(("rw", "kin"))
    results = []
    for item in locations:
        assessment = assess_location_ml(db, item["latitude"], item["longitude"], business_category, item.get("radius_meters", 500), locale=locale)
        score = assessment.get("overall", {}).get("opportunity_score", 0)
        factors = assessment.get("factors", {})
        default_label = f"Ahantu {len(results)+1}" if rw else f"Location {len(results)+1}"
        results.append({
            "label": item.get("label") or default_label,
            "latitude": item["latitude"],
            "longitude": item["longitude"],
            "opportunity_score": score,
            "opportunity_type": assessment.get("overall", {}).get("opportunity_type"),
            "confidence_score": assessment.get("overall", {}).get("confidence_score"),
            "demand_score": factors.get("demand_score"),
            "accessibility_score": factors.get("accessibility_score"),
            "commercial_activity_score": factors.get("commercial_activity_score"),
            "competition_pressure": factors.get("competition_pressure"),
            "recommendation": assessment.get("recommendation"),
        })
    results.sort(key=lambda r: r["opportunity_score"], reverse=True)
    winner = results[0] if results else None
    if winner:
        summary = f"{winner['label']} ni ho hafite ikimenyetso gikomeye kurusha ahandi ku {business_category.replace('_', ' ')}." if rw \
            else f"{winner['label']} has the strongest overall signal for {business_category.replace('_', ' ')}."
    else:
        summary = "Ongeraho ahantu kugira ngo ugereranye." if rw else "Add locations to compare."
    return {
        "business_category": business_category,
        "locations": results,
        "best_location": winner,
        "summary": summary,
    }
