from __future__ import annotations

import math
from dataclasses import asdict
from typing import Any

from app.geo.feature_extraction import LocationFeatures
from app.core.categories import BUSINESS_CATEGORIES, category_payload, normalise_category

KIGALI_CENTER = {"latitude": -1.9441, "longitude": 30.0619}

CATEGORIES = category_payload('en')

CATEGORY_WEIGHTS: dict[str, dict[str, float]] = {
    c.key: {
        'demand': c.weights['demand'],
        'access': c.weights['access'],
        'commercial': c.weights['activity'],
        'competition': c.weights['competition'],
        'welfare': c.weights['welfare'],
    } for c in BUSINESS_CATEGORIES
}

KIGALI_ZONES = [
    {"grid_id": "KGL-KIM-01", "name": "Kimironko Market Edge", "district": "Gasabo", "latitude": -1.9368, "longitude": 30.1306, "demand": 84, "access": 82, "commercial": 89, "competition": 72, "confidence": 78},
    {"grid_id": "KGL-REM-02", "name": "Remera Transport Corridor", "district": "Gasabo", "latitude": -1.9591, "longitude": 30.1084, "demand": 78, "access": 88, "commercial": 81, "competition": 66, "confidence": 74},
    {"grid_id": "KGL-KAC-03", "name": "Kacyiru Mixed-Use Pocket", "district": "Gasabo", "latitude": -1.9302, "longitude": 30.0741, "demand": 69, "access": 72, "commercial": 74, "competition": 48, "confidence": 70},
    {"grid_id": "KGL-NYA-04", "name": "Nyamirambo Residential Cluster", "district": "Nyarugenge", "latitude": -1.9825, "longitude": 30.0377, "demand": 86, "access": 66, "commercial": 62, "competition": 42, "confidence": 66},
    {"grid_id": "KGL-GIK-05", "name": "Gikondo Commercial Strip", "district": "Kicukiro", "latitude": -1.9746, "longitude": 30.0761, "demand": 72, "access": 78, "commercial": 77, "competition": 57, "confidence": 69},
    {"grid_id": "KGL-KAN-06", "name": "Kanombe Growth Area", "district": "Kicukiro", "latitude": -1.9707, "longitude": 30.1483, "demand": 65, "access": 70, "commercial": 55, "competition": 34, "confidence": 58},
    {"grid_id": "KGL-MUH-07", "name": "Muhima Service Zone", "district": "Nyarugenge", "latitude": -1.9389, "longitude": 30.0534, "demand": 74, "access": 84, "commercial": 82, "competition": 69, "confidence": 76},
    {"grid_id": "KGL-KAG-08", "name": "Kagarama Residential Edge", "district": "Kicukiro", "latitude": -1.9901, "longitude": 30.1085, "demand": 70, "access": 64, "commercial": 58, "competition": 31, "confidence": 61},
    {"grid_id": "KGL-GIS-09", "name": "Gisozi Residential Corridor", "district": "Gasabo", "latitude": -1.9162, "longitude": 30.0825, "demand": 73, "access": 68, "commercial": 60, "competition": 39, "confidence": 62},
    {"grid_id": "KGL-KIC-10", "name": "Kicukiro Centre", "district": "Kicukiro", "latitude": -1.9721, "longitude": 30.1009, "demand": 77, "access": 76, "commercial": 75, "competition": 59, "confidence": 71},
    {"grid_id": "KGL-CBD-11", "name": "Nyarugenge Commercial Core", "district": "Nyarugenge", "latitude": -1.9447, "longitude": 30.0605, "demand": 67, "access": 91, "commercial": 94, "competition": 83, "confidence": 81},
    {"grid_id": "KGL-KAB-12", "name": "Kabeza Residential Access Point", "district": "Kicukiro", "latitude": -1.9667, "longitude": 30.1265, "demand": 68, "access": 69, "commercial": 57, "competition": 33, "confidence": 60},
]


def clamp(value: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, value))


def category_label(key: str) -> str:
    category = normalise_category(key)
    match = next((c for c in CATEGORIES if c['key'] == category), None)
    return match['label'] if match else category.replace('_', ' ').title()


def _category_adjustment(category: str, zone: dict[str, Any]) -> tuple[float, float, float, float]:
    """Return demand/access/commercial/competition adjustments by category."""
    cat = normalise_category(category)
    commercial_bias = {
        "cafe": 7, "restaurant": 6, "retail": 5, "mobile_money": 4,
        "pharmacy": 1, "grocery": -1, "salon": 2, "barbershop": 1, "beauty_salon": 3,
    }.get(cat, 0)
    demand_bias = {
        "grocery": 8, "salon": 5, "beauty_salon": 4, "barbershop": 3,
        "pharmacy": 5, "cafe": 0, "restaurant": 1, "retail": 2, "mobile_money": 4,
    }.get(cat, 0)
    access_bias = {"pharmacy": 6, "restaurant": 4, "mobile_money": 3, "retail": 2, "cafe": 2}.get(cat, 0)
    competition_bias = {
        "salon": 10, "barbershop": 8, "beauty_salon": 9, "restaurant": 6,
        "cafe": 5, "pharmacy": 3, "grocery": 4, "retail": 5, "mobile_money": 4,
    }.get(cat, 0)
    return demand_bias, access_bias, commercial_bias, competition_bias


def score_zone(zone: dict[str, Any], category: str) -> dict[str, Any]:
    weights = CATEGORY_WEIGHTS.get(normalise_category(category), CATEGORY_WEIGHTS["pharmacy"])
    demand_adj, access_adj, commercial_adj, competition_adj = _category_adjustment(category, zone)
    demand = clamp(zone["demand"] + demand_adj)
    access = clamp(zone["access"] + access_adj)
    commercial = clamp(zone["commercial"] + commercial_adj)
    competition = clamp(zone["competition"] + competition_adj)
    welfare = clamp((demand * 0.55) + (commercial * 0.25) + (100 - competition) * 0.20)
    opportunity = (
        demand * weights["demand"]
        + access * weights["access"]
        + commercial * weights["commercial"]
        + (100 - competition) * weights["competition"]
        + welfare * weights["welfare"]
    )
    opportunity = round(clamp(opportunity), 2)
    confidence = round(clamp(zone["confidence"] + (3 if category in {"salon", "barbershop", "beauty_salon"} else -2)), 2)
    if opportunity >= 78 and competition < 68:
        opportunity_type = "Prime opportunity"
        badge = "High-opportunity zone"
    elif opportunity >= 68 and competition < 55:
        opportunity_type = "Underserved opportunity"
        badge = "Underserved pocket"
    elif opportunity >= 65 and competition >= 68:
        opportunity_type = "Strong demand, crowded market"
        badge = "High demand / high competition"
    elif opportunity >= 52:
        opportunity_type = "Worth comparing"
        badge = "Promising but needs validation"
    else:
        opportunity_type = "Weak signal"
        badge = "Low priority"
    return {
        **zone,
        "business_category": category,
        "display_category": category_label(category),
        "opportunity_score": opportunity,
        "demand_score": round(demand, 2),
        "accessibility_score": round(access, 2),
        "access_score": round(access, 2),
        "commercial_activity_score": round(commercial, 2),
        "competition_pressure": round(competition, 2),
        "competition_score": round(competition, 2),
        "confidence_score": confidence,
        "opportunity_type": opportunity_type,
        "experience_badge": badge,
        "zone_key": _zone_key(opportunity, competition),
        "risk_level": "high" if competition >= 72 else "medium" if competition >= 50 else "low",
        "explanation": build_explanation(opportunity, demand, access, commercial, competition, confidence, category),
    }


def _zone_key(opportunity: float, competition: float) -> str:
    if opportunity >= 72 and competition < 60:
        return "high_opportunity"
    if opportunity >= 66 and competition < 45:
        return "underserved"
    if opportunity >= 60 and competition >= 70:
        return "saturated"
    if opportunity < 50:
        return "weak_demand"
    return "emerging"


def build_explanation(opportunity: float, demand: float, access: float, commercial: float, competition: float, confidence: float, category: str) -> dict[str, Any]:
    strengths: list[str] = []
    risks: list[str] = []
    if demand >= 70:
        strengths.append("Strong nearby demand indicators")
    else:
        risks.append("Demand signal should be checked on-site")
    if access >= 70:
        strengths.append("Good access from roads, movement corridors or service proximity")
    else:
        risks.append("Access may reduce walk-in potential")
    if commercial >= 70:
        strengths.append("Active surrounding commercial environment")
    if competition >= 70:
        risks.append(f"High same-category pressure for {category_label(category).lower()}")
    elif competition <= 45:
        strengths.append("Competition pressure appears manageable")
    if confidence < 55:
        risks.append("Data confidence is moderate; field validation is recommended")
    return {
        "headline": _headline(opportunity, competition, category),
        "strengths": strengths,
        "risks": risks,
        "next_steps": [
            "Compare this site with at least two nearby alternatives.",
            "Check informal competitors and visible customer flow before making a rent decision.",
            "Visit during morning, midday and evening to validate movement patterns.",
        ],
    }


def _headline(opportunity: float, competition: float, category: str) -> str:
    label = category_label(category).lower()
    if opportunity >= 78 and competition < 65:
        return f"This area looks promising for a {label}."
    if opportunity >= 65 and competition >= 70:
        return f"Demand looks strong, but the {label} market appears crowded."
    if opportunity >= 60:
        return f"This location is worth comparing for a {label}."
    return f"This location needs stronger evidence before choosing it for a {label}."


def demo_zones(category: str = "salon", limit: int | None = None, district: str | None = None) -> list[dict[str, Any]]:
    zones = [score_zone(z, category) for z in KIGALI_ZONES if not district or z["district"].lower() == district.lower()]
    zones.sort(key=lambda r: (r["opportunity_score"], r["confidence_score"]), reverse=True)
    return zones[:limit] if limit else zones


def nearest_zone(latitude: float, longitude: float, category: str = "salon") -> dict[str, Any]:
    def dist(z: dict[str, Any]) -> float:
        return math.hypot((latitude - z["latitude"]) * 111_000, (longitude - z["longitude"]) * 111_000)
    raw = min(KIGALI_ZONES, key=dist)
    zone = score_zone(raw, category)
    zone["distance_to_grid_m"] = round(dist(raw), 1)
    return zone


def features_from_zone(latitude: float, longitude: float, category: str) -> LocationFeatures:
    zone = nearest_zone(latitude, longitude, category)
    risk = clamp((zone["competition_pressure"] * 0.55) + ((100 - zone["accessibility_score"]) * 0.25) + ((100 - zone["demand_score"]) * 0.20))
    return LocationFeatures(
        demand_score=zone["demand_score"],
        accessibility_score=zone["accessibility_score"],
        competition_pressure=zone["competition_pressure"],
        commercial_activity_score=zone["commercial_activity_score"],
        risk_score=round(risk, 2),
        confidence_score=zone["confidence_score"],
        population_density_500m=round(zone["demand_score"] * 120, 2),
        population_density_1000m=round(zone["demand_score"] * 170, 2),
        commercial_poi_count_500m=int(zone["commercial_activity_score"] // 4),
        competitor_count_300m=max(0, int(zone["competition_pressure"] // 18)),
        competitor_count_500m=max(0, int(zone["competition_pressure"] // 11)),
        competitor_count_1000m=max(0, int(zone["competition_pressure"] // 6)),
        market_distance_m=max(90, round(1800 - (zone["commercial_activity_score"] * 15), 2)),
        nearest_main_road_m=max(30, round(1300 - (zone["accessibility_score"] * 12), 2)),
        bus_stop_count_500m=max(0, int(zone["accessibility_score"] // 18)),
    )


def geojson_for_zones(category: str = "salon", layer: str = "opportunity") -> dict[str, Any]:
    features = []
    for zone in demo_zones(category):
        metric = {
            "opportunity": zone["opportunity_score"],
            "demand": zone["demand_score"],
            "access": zone["accessibility_score"],
            "commercial": zone["commercial_activity_score"],
            "competition": zone["competition_pressure"],
            "confidence": zone["confidence_score"],
        }.get(layer, zone["opportunity_score"])
        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [zone["longitude"], zone["latitude"]]},
            "properties": {**zone, "active_layer": layer, "active_score": metric},
        })
    return {"type": "FeatureCollection", "features": features}


def category_profiles() -> list[dict[str, Any]]:
    profiles = []
    for cat in CATEGORIES:
        weights = CATEGORY_WEIGHTS.get(cat["key"], CATEGORY_WEIGHTS["salon"])
        profiles.append({
            "category_key": cat["key"],
            "display_name": cat["label"],
            "description": cat["description"],
            "confidence": cat["confidence"],
            "weights": weights,
            "confidence_threshold": 45 if cat["confidence"] == "medium" else 55,
        })
    return profiles
