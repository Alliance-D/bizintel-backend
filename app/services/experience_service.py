from __future__ import annotations

import json
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.services.demo_data import CATEGORIES, demo_zones, nearest_zone, score_zone


def get_experience_manifest(db: Session) -> dict[str, Any]:
    categories = [
        {"key": c["key"], "label": c["label"], "description": c["description"], "confidence": c["confidence"]}
        for c in CATEGORIES
    ]
    return {
        "workspace": "Business opportunity workspace",
        "default_category": "salon",
        "default_center": {"latitude": -1.9441, "longitude": 30.0619, "zoom": 12},
        "categories": categories,
        "layers": [
            {"key": "opportunity", "label": "Opportunity", "description": "Overall ML-ranked opportunity potential."},
            {"key": "demand", "label": "Demand", "description": "Residential, population and customer-potential signal."},
            {"key": "access", "label": "Access", "description": "Road, public transport and service-access signal."},
            {"key": "commercial", "label": "Commercial activity", "description": "Markets, shops, services and surrounding business activity."},
            {"key": "competition", "label": "Competition", "description": "Same-category saturation and competitor pressure."},
            {"key": "confidence", "label": "Confidence", "description": "How complete the supporting data is for this area."},
        ],
        "quick_actions": [
            "Assess this location",
            "Compare nearby alternatives",
            "Save to watchlist",
            "Create field visit checklist",
        ],
    }


def get_cell_insight(db: Session, latitude: float, longitude: float, business_category: str, radius_meters: int = 500) -> dict[str, Any]:
    try:
        row = db.execute(text("""
            SELECT * FROM ml.v_opportunity_experience_cells
            WHERE business_category = :category
            ORDER BY geom <-> ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)
            LIMIT 1
        """), {"category": business_category, "lon": longitude, "lat": latitude}).mappings().first()
        if row:
            return _insight_payload(dict(row), latitude, longitude, business_category)
    except Exception:
        db.rollback()
    return _insight_payload(nearest_zone(latitude, longitude, business_category), latitude, longitude, business_category)


def get_category_story(db: Session, business_category: str) -> dict[str, Any]:
    try:
        summary = db.execute(text("""
            SELECT COUNT(*) AS cells, AVG(opportunity_score) AS avg_opportunity, MAX(opportunity_score) AS max_opportunity,
                   AVG(demand_score) AS avg_demand, AVG(competition_pressure) AS avg_competition, AVG(confidence_score) AS avg_confidence
            FROM ml.ml_opportunity_predictions
            WHERE business_category = :category
        """), {"category": business_category}).mappings().first()
        top = db.execute(text("""
            SELECT grid_id, opportunity_score, opportunity_type, confidence_score, ST_Y(geom) AS latitude, ST_X(geom) AS longitude
            FROM ml.ml_opportunity_predictions
            WHERE business_category = :category
            ORDER BY opportunity_score DESC, confidence_score DESC LIMIT 8
        """), {"category": business_category}).mappings().all()
        if summary and summary.get("cells"):
            return {"business_category": business_category, "summary": dict(summary), "top_zones": [dict(r) for r in top], "narrative": _category_narrative(business_category, summary)}
    except Exception:
        db.rollback()
    zones = demo_zones(business_category, limit=8)
    avg = round(sum(z["opportunity_score"] for z in zones) / len(zones), 2)
    return {
        "business_category": business_category,
        "summary": {"cells": len(zones), "avg_opportunity": avg, "max_opportunity": max(z["opportunity_score"] for z in zones), "avg_competition": round(sum(z["competition_pressure"] for z in zones)/len(zones),2)},
        "top_zones": zones,
        "narrative": _category_narrative(business_category, {"avg_opportunity": avg, "avg_competition": sum(z["competition_pressure"] for z in zones)/len(zones), "cells": len(zones)}),
    }


def get_recommendation_feed(db: Session, business_category: str, limit: int = 12) -> dict[str, Any]:
    try:
        rows = db.execute(text("""
            SELECT grid_id, business_category, opportunity_score, demand_score, accessibility_score,
                   competition_pressure, confidence_score, experience_badge, recommended_next_step,
                   ST_Y(geom) AS latitude, ST_X(geom) AS longitude
            FROM ml.v_opportunity_experience_cells
            WHERE business_category = :category
            ORDER BY opportunity_score DESC, confidence_score DESC LIMIT :limit
        """), {"category": business_category, "limit": limit}).mappings().all()
        if rows:
            return {"business_category": business_category, "items": [dict(r) for r in rows]}
    except Exception:
        db.rollback()
    items = []
    for z in demo_zones(business_category, limit=limit):
        items.append({
            **z,
            "recommended_next_step": "Compare this area with nearby alternatives, then validate visible competitors and customer movement on-site.",
        })
    return {"business_category": business_category, "items": items}


def track_experience_event(db: Session, event_name: str, business_category: str | None, latitude: float | None, longitude: float | None, payload: dict, session_id: str | None) -> dict[str, Any]:
    try:
        row = db.execute(text("""
            INSERT INTO app.user_experience_events (event_name, business_category, latitude, longitude, payload, session_id)
            VALUES (:event_name, :business_category, :latitude, :longitude, CAST(:payload AS jsonb), :session_id)
            RETURNING id, created_at
        """), {
            "event_name": event_name, "business_category": business_category, "latitude": latitude, "longitude": longitude,
            "payload": json.dumps(payload or {}), "session_id": session_id,
        }).mappings().first()
        db.commit()
        return {"saved": True, "event_id": row["id"], "created_at": row["created_at"]}
    except Exception:
        db.rollback()
        return {"saved": False, "event_name": event_name}


def _insight_payload(row: dict[str, Any], latitude: float, longitude: float, category: str) -> dict[str, Any]:
    opportunity = float(row.get("opportunity_score") or 0)
    demand = float(row.get("demand_score") or 0)
    access = float(row.get("accessibility_score") or row.get("access_score") or 0)
    commercial = float(row.get("commercial_activity_score") or 0)
    competition = float(row.get("competition_pressure") or row.get("competition_score") or 0)
    confidence = float(row.get("confidence_score") or 0)
    explanation = row.get("explanation") or {}
    return {
        "business_category": category,
        "latitude": latitude,
        "longitude": longitude,
        "grid_id": row.get("grid_id"),
        "headline": (explanation.get("headline") if isinstance(explanation, dict) else None) or _headline(row.get("experience_badge"), category),
        "badge": row.get("experience_badge") or row.get("opportunity_type"),
        "recommended_next_step": row.get("recommended_next_step") or "Compare this location and validate informal competition before deciding.",
        "scores": {
            "opportunity": opportunity, "demand": demand, "accessibility": access, "commercial_activity": commercial,
            "competition_pressure": competition, "confidence": confidence,
        },
        "competition": {"within_300m": int(competition // 18), "within_500m": int(competition // 11), "within_1000m": int(competition // 6)},
        "insight_cards": _insight_cards(opportunity, demand, access, commercial, competition, confidence),
        "actions": _actions(opportunity, competition, confidence),
        "explanation": explanation,
    }


def _headline(badge: str | None, category: str) -> str:
    label = category.replace("_", " ")
    if badge in {"Prime Opportunity", "High-opportunity zone"}:
        return f"This looks like a strong {label} opportunity zone."
    if badge in {"Underserved Pocket", "Underserved pocket"}:
        return f"This area may be underserved for {label} demand."
    if badge in {"High Demand / Crowded", "High demand / high competition"}:
        return f"Demand is strong, but {label} competition appears crowded."
    return f"This location is worth comparing for {label}."


def _insight_cards(opportunity: float, demand: float, access: float, commercial: float, competition: float, confidence: float) -> list[dict[str, Any]]:
    return [
        {"title": "Opportunity", "value": opportunity, "tone": "emerald" if opportunity >= 70 else "amber" if opportunity >= 50 else "rose", "body": "Overall ML-ranked opportunity potential."},
        {"title": "Demand", "value": demand, "tone": "sky", "body": "Population, household and local customer-potential signal."},
        {"title": "Access", "value": access, "tone": "violet", "body": "Road, transport and service-access signal."},
        {"title": "Commercial activity", "value": commercial, "tone": "cyan", "body": "Nearby markets, shops and commercial anchors."},
        {"title": "Competition", "value": competition, "tone": "rose" if competition >= 70 else "amber" if competition >= 45 else "emerald", "body": "Same-category saturation pressure."},
        {"title": "Confidence", "value": confidence, "tone": "emerald" if confidence >= 65 else "amber" if confidence >= 45 else "rose", "body": "Completeness and reliability of supporting layers."},
    ]


def _actions(opportunity: float, competition: float, confidence: float) -> list[str]:
    actions = ["Compare this point with at least two nearby alternatives."]
    if opportunity >= 75:
        actions.append("Schedule a field visit before rent negotiations.")
    if competition >= 70:
        actions.append("Check if differentiation or niche positioning is possible.")
    else:
        actions.append("Verify whether informal competitors are missing from mapped data.")
    if confidence < 55:
        actions.append("Collect a validation note: pedestrian activity, visible customers and shop availability.")
    return actions


def _category_narrative(category: str, summary: Any) -> str:
    if not summary or not summary.get("cells"):
        return "Prediction surfaces are not available yet for this category."
    avg = float(summary.get("avg_opportunity") or 0)
    comp = float(summary.get("avg_competition") or 0)
    label = category.replace("_", " ")
    if avg >= 65 and comp < 60:
        return f"{label.title()} opportunities look favorable where demand and access overlap with manageable competition."
    if comp >= 65:
        return f"{label.title()} opportunities need careful interpretation because competition pressure is elevated in many mapped cells."
    return f"{label.title()} opportunity is uneven across Kigali; prioritize areas with strong demand and confidence."
