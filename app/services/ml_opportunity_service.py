from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.services.location_labels import location_label
from app.services.geography_service import nearest_landmark



def list_category_profiles(db: Session) -> dict[str, Any]:
    """Return summary profiles for each business category across the scored grid."""
    try:
        rows = db.execute(text("""
            SELECT category_key, display_name, description, demand_weight, access_weight,
                   commercial_weight, competition_weight, welfare_weight,
                   min_confidence_threshold, is_active
            FROM curated.business_category_profiles
            WHERE is_active = TRUE
            ORDER BY display_name
        """)).mappings().all()
        if rows:
            return {"categories": [{
                "category_key": r["category_key"],
                "display_name": r["display_name"],
                "description": r["description"],
                "weights": {
                    "demand": float(r["demand_weight"] or 0),
                    "access": float(r["access_weight"] or 0),
                    "commercial": float(r["commercial_weight"] or 0),
                    "competition": float(r["competition_weight"] or 0),
                    "welfare": float(r["welfare_weight"] or 0),
                },
                "confidence_threshold": r["min_confidence_threshold"],
            } for r in rows]}
    except Exception:
        db.rollback()
    return {"categories": [], "source": "database_unavailable"}


def assess_location_ml(db: Session, latitude: float, longitude: float, business_category: str, radius_meters: int = 500, locale: str | None = None) -> dict[str, Any]:
    """Assess a point: read the nearest scored grid cell's cached prediction and
    recount competitors live at the exact coordinate, returning the combined
    payload (overall gap, factors, signals, competitors, landmark, narrative)."""
    try:
        prediction = db.execute(text("SELECT * FROM ml.get_ml_prediction_near(:lon, :lat, :category)"), {
            "lon": longitude, "lat": latitude, "category": business_category
        }).mappings().first()
        if prediction:
            competitors = _competitors(db, longitude, latitude, business_category, radius_meters)
            signals_raw = _grid_signals(db, prediction.get("grid_id"), business_category)
            payload = _prediction_payload(dict(prediction), latitude, longitude, business_category, competitors, locale=locale, signals_raw=signals_raw)
            payload["landmark"] = nearest_landmark(db, latitude, longitude, locale)
            return payload
    except Exception:
        db.rollback()

    rw = _is_kinyarwanda(locale)
    return {
        "status": "unavailable",
        "source": "no_ml_prediction_cache",
        "business_category": business_category,
        "latitude": latitude,
        "longitude": longitude,
        "location_label": location_label(None, None, None, None, locale),
        "overall": {"gap_score": 0, "opportunity_score": 0, "confidence_score": 0, "opportunity_type": _localize_opportunity_type("Prediction unavailable", locale), "opportunity_rank": None, "expected_count": None, "observed_count": None, "gap": None},
        "factors": {"demand_score": 0, "accessibility_score": 0, "commercial_activity_score": 0, "competition_pressure": 0},
        "signals": _build_signals({}, 0, None, 0, locale),
        "competition": {"within_300m": 0, "within_500m": 0, "within_1000m": 0},
        "nearby_context": [],
        "explanation": {"summary": "Nta iteganya ryabonetse kuri aha hantu n'ubu bwoko." if rw else "No prediction was found for this location and category."},
        "risk_notes": ["Amakuru y'iteganya ry'ubu ntaboneka." if rw else "Live prediction data is unavailable."],
        "recommendation": "Ongera ufungure ikarita cyangwa ugerageze ahandi hantu hafi." if rw else "Refresh the map or try another nearby location.",
    }


def _competitors(db: Session, longitude: float, latitude: float, category: str, radius_meters: int) -> dict[str, int]:
    """Count same-category competitors within 300m/500m/1000m of an exact point."""
    try:
        row = db.execute(text("""
            SELECT
              COUNT(*) FILTER (WHERE ST_DWithin(geom::geography, ST_SetSRID(ST_MakePoint(:lon,:lat),4326)::geography, 300)) AS within_300m,
              COUNT(*) FILTER (WHERE ST_DWithin(geom::geography, ST_SetSRID(ST_MakePoint(:lon,:lat),4326)::geography, 500)) AS within_500m,
              COUNT(*) FILTER (WHERE ST_DWithin(geom::geography, ST_SetSRID(ST_MakePoint(:lon,:lat),4326)::geography, 1000)) AS within_1000m
            FROM curated.osm_poi_features
            WHERE category_key = :category
        """), {"lon": longitude, "lat": latitude, "category": category, "radius": radius_meters}).mappings().first()
        if row:
            return {"within_300m": int(row["within_300m"] or 0), "within_500m": int(row["within_500m"] or 0), "within_1000m": int(row["within_1000m"] or 0)}
    except Exception:
        db.rollback()
    return {"within_300m": 0, "within_500m": 0, "within_1000m": 0}


def list_nearby_competitors(db: Session, latitude: float, longitude: float, category: str, radius_meters: int = 1000, limit: int = 40) -> list[dict[str, Any]]:
    """Individual competitor points (name + coordinates) for the report's map -
    _competitors() above only returns aggregate counts, not positions."""
    try:
        rows = db.execute(text("""
            SELECT name, category_key, ST_Y(geom) AS latitude, ST_X(geom) AS longitude,
                   ST_Distance(geom::geography, ST_SetSRID(ST_MakePoint(:lon,:lat),4326)::geography) AS distance_m
            FROM curated.osm_poi_features
            WHERE category_key = :category
              AND ST_DWithin(geom::geography, ST_SetSRID(ST_MakePoint(:lon,:lat),4326)::geography, :radius)
            ORDER BY distance_m
            LIMIT :limit
        """), {"lon": longitude, "lat": latitude, "category": category, "radius": radius_meters, "limit": limit}).mappings().all()
        return [{
            "name": r["name"],
            "category_key": r["category_key"],
            "latitude": float(r["latitude"]),
            "longitude": float(r["longitude"]),
            "distance_m": round(float(r["distance_m"]), 1),
        } for r in rows]
    except Exception:
        db.rollback()
        return []


def list_nearby_pois(db: Session, latitude: float, longitude: float, category_keys: list[str], radius_meters: int = 1000, limit: int = 40) -> list[dict[str, Any]]:
    """Individual POIs of one or more categories, with coordinates and distance -
    used for the report map layers and the "what's nearby" lists (foot-traffic
    anchors, complementary businesses). Generalises list_nearby_competitors."""
    try:
        rows = db.execute(text("""
            SELECT name, category_key, ST_Y(geom) AS latitude, ST_X(geom) AS longitude,
                   ST_Distance(geom::geography, ST_SetSRID(ST_MakePoint(:lon,:lat),4326)::geography) AS distance_m
            FROM curated.osm_poi_features
            WHERE category_key = ANY(:cats)
              AND ST_DWithin(geom::geography, ST_SetSRID(ST_MakePoint(:lon,:lat),4326)::geography, :radius)
            ORDER BY distance_m
            LIMIT :limit
        """), {"lon": longitude, "lat": latitude, "cats": list(category_keys), "radius": radius_meters, "limit": limit}).mappings().all()
        return [{
            "name": r["name"],
            "category_key": r["category_key"],
            "latitude": float(r["latitude"]),
            "longitude": float(r["longitude"]),
            "distance_m": round(float(r["distance_m"]), 1),
        } for r in rows]
    except Exception:
        db.rollback()
        return []


def _grid_signals(db: Session, grid_id: str | None, category: str) -> dict[str, Any]:
    """Raw area fundamentals from the nearest scored grid cell - population,
    commercial activity, and the foot-traffic anchor counts the model used.
    These explain the score to the user; the prediction row itself only carries
    the derived scores, not these raw inputs."""
    if not grid_id:
        return {}
    try:
        row = db.execute(text("""
            SELECT population_density_1000m, sector_population, employment_rate, income_proxy,
                   commercial_poi_count_500m, complementary_poi_count_500m, demand_generator_count_1000m,
                   bus_stop_count_500m, nearest_bus_stop_m, school_count_1000m,
                   health_facility_count_1000m, market_distance_m
            FROM ml.grid_category_features
            WHERE grid_id = :grid_id AND business_category = :category
            LIMIT 1
        """), {"grid_id": grid_id, "category": category}).mappings().first()
        if row:
            return {k: (float(v) if v is not None else None) for k, v in dict(row).items()}
    except Exception:
        db.rollback()
    return {}


def _activity_level(score: float, locale: str | None = None) -> str:
    """Bucket a commercial-activity score into High/Medium/Low, localized."""
    rw = _is_kinyarwanda(locale)
    if score >= 60:
        return "Byinshi" if rw else "High"
    if score >= 30:
        return "Bigereranije" if rw else "Medium"
    return "Bike" if rw else "Low"


def _build_signals(raw: dict[str, Any], commercial_score: float, expected_count: float | None, observed_count: float, locale: str | None = None) -> dict[str, Any]:
    """Assemble the plain-language signal block shown on the report (people nearby,
    activity level, anchors, distances, expected/observed counts) from raw features."""
    density = raw.get("population_density_1000m")
    return {
        # population density is people/km2; within a ~1km radius that's ~pi km2,
        # a rough but honest "people nearby" figure for a plain-language report.
        "people_within_1km": round(density * 3.14159) if density else None,
        "population_density_1000m": round(density) if density else None,
        "sector_population": round(raw["sector_population"]) if raw.get("sector_population") else None,
        "commercial_activity_level": _activity_level(commercial_score, locale),
        "commercial_poi_count_500m": int(raw["commercial_poi_count_500m"]) if raw.get("commercial_poi_count_500m") is not None else None,
        "complementary_poi_count_500m": int(raw["complementary_poi_count_500m"]) if raw.get("complementary_poi_count_500m") is not None else None,
        "anchor_count_1000m": int(raw["demand_generator_count_1000m"]) if raw.get("demand_generator_count_1000m") is not None else None,
        "bus_stop_count_500m": int(raw["bus_stop_count_500m"]) if raw.get("bus_stop_count_500m") is not None else None,
        "nearest_bus_stop_m": round(raw["nearest_bus_stop_m"]) if raw.get("nearest_bus_stop_m") else None,
        "school_count_1000m": int(raw["school_count_1000m"]) if raw.get("school_count_1000m") is not None else None,
        "health_facility_count_1000m": int(raw["health_facility_count_1000m"]) if raw.get("health_facility_count_1000m") is not None else None,
        "market_distance_m": round(raw["market_distance_m"]) if raw.get("market_distance_m") else None,
        "expected_count": round(float(expected_count), 1) if expected_count is not None else None,
        "observed_count": observed_count,
    }


def _prediction_payload(prediction: dict[str, Any], latitude: float, longitude: float, category: str, competitors: dict[str, int], source: str = "ml_prediction_cache", locale: str | None = None, signals_raw: dict[str, Any] | None = None) -> dict[str, Any]:
    """Shape a cached grid prediction plus live competitor counts into the API
    payload, swapping the live observed count in so the shown gap reflects the
    exact clicked point."""
    gap_score = round(float(prediction.get("opportunity_score") or 0), 2)  # gap percentile within category (0-100), see train_and_score_opportunity_model.py
    confidence = round(float(prediction.get("confidence_score") or 0), 2)
    competition = round(float(prediction.get("competition_pressure") or 0), 2)
    access = round(float(prediction.get("accessibility_score") or prediction.get("access_score") or 0), 2)
    commercial = round(float(prediction.get("commercial_activity_score") or 0), 2)
    demand = round(float(prediction.get("demand_score") or 0), 2)
    opportunity_type = prediction.get("opportunity_type") or "Worth comparing"

    explanation = dict(prediction.get("explanation") or {})
    gap_details = explanation.get("gap_details") or {}
    expected_count = gap_details.get("expected_count")
    # observed_count from the nearest scored grid cell is approximate (that
    # cell may be a few hundred metres away); competitors["within_1000m"] is
    # computed live at the exact clicked point, so it's the more trustworthy
    # number to actually show as "observed" - swap it in when available.
    observed_count = float(competitors.get("within_1000m", gap_details.get("observed_count") or 0))
    gap = (expected_count - observed_count) if expected_count is not None else gap_details.get("gap")

    return {
        "status": "ready",
        "source": source,
        "business_category": category,
        "latitude": latitude,
        "longitude": longitude,
        "nearest_grid_id": prediction.get("grid_id"),
        "distance_to_grid_m": prediction.get("distance_m") or prediction.get("distance_to_grid_m"),
        "model_version_id": prediction.get("model_version_id"),
        "district": prediction.get("district"),
        "sector": prediction.get("sector"),
        "cell": prediction.get("cell"),
        "village": prediction.get("village"),
        "location_label": location_label(
            prediction.get("district"), prediction.get("sector"),
            prediction.get("cell"), prediction.get("village"), locale,
        ),
        "overall": {
            "gap_score": gap_score,
            "opportunity_score": gap_score,  # kept for callers not yet migrated to gap_score
            "opportunity_rank": prediction.get("opportunity_rank"),
            "opportunity_type": _localize_opportunity_type(opportunity_type, locale),
            "confidence_score": confidence,
            "expected_count": round(float(expected_count), 2) if expected_count is not None else None,
            "observed_count": observed_count,
            "gap": round(float(gap), 2) if gap is not None else None,
        },
        "factors": {
            "demand_score": demand,
            "accessibility_score": access,
            "commercial_activity_score": commercial,
            "competition_pressure": competition,
        },
        "signals": _build_signals(signals_raw or {}, commercial, expected_count, observed_count, locale),
        "competition": competitors,
        "nearby_context": [],
        "explanation": explanation,
        "risk_notes": _risk_notes(gap_score, competition, confidence, access, locale),
        "recommendation": _recommendation(gap_score, confidence, competition, expected_count, observed_count, locale),
    }


def list_top_opportunity_zones(db: Session, business_category: str, limit: int = 25) -> dict[str, Any]:
    """Return the top-ranked opportunity cells for a category."""
    try:
        rows = db.execute(text("""
            SELECT grid_id, business_category, opportunity_score, opportunity_rank, opportunity_type,
                   confidence_score, ST_Y(geom) AS latitude, ST_X(geom) AS longitude, explanation
            FROM ml.ml_opportunity_predictions
            WHERE business_category = :category
            ORDER BY opportunity_score DESC, confidence_score DESC
            LIMIT :limit
        """), {"category": business_category, "limit": limit}).mappings().all()
        if rows:
            return {"business_category": business_category, "zones": [dict(r) for r in rows]}
    except Exception:
        db.rollback()
    return {"business_category": business_category, "zones": [], "source": "database_unavailable"}


def get_ml_engine_status(db: Session) -> dict[str, Any]:
    """Report ML readiness: prediction-cache sizes, active categories and coverage."""
    try:
        counts = db.execute(text("""
            SELECT
              (SELECT COUNT(*) FROM curated.osm_poi_features) AS osm_pois,
              (SELECT COUNT(*) FROM ml.grid_category_features) AS grid_features,
              (SELECT COUNT(*) FROM ml.ml_opportunity_predictions) AS predictions,
              (SELECT COUNT(*) FROM curated.business_category_profiles WHERE is_active = TRUE) AS active_categories
        """)).mappings().first()
        by_category = db.execute(text("""
            SELECT business_category, COUNT(*) AS prediction_rows, AVG(opportunity_score) AS avg_score, MAX(opportunity_score) AS max_score
            FROM ml.ml_opportunity_predictions
            GROUP BY business_category ORDER BY business_category
        """)).mappings().all()
        return {"mode": "ml_cache", "readiness": dict(counts or {}), "prediction_summary_by_category": [dict(r) for r in by_category]}
    except Exception:
        db.rollback()
        return {
            "mode": "unavailable",
            "readiness": {"osm_pois": 0, "grid_features": 0, "predictions": 0, "active_categories": 0},
            "prediction_summary_by_category": [],
            "message": "Prediction tables are unavailable.",
        }


def _is_kinyarwanda(locale: str | None) -> bool:
    """True when the locale string denotes Kinyarwanda."""
    return (locale or "").lower().startswith(("rw", "kin"))


_OPPORTUNITY_TYPE_RW = {
    "Underserved": "Ahatarigera hagerwaho bihagije",
    "Room to grow": "Ahakiri umwanya wo gukura",
    "Balanced": "Ahangana",
    "Saturated": "Ahuzuye",
    "Worth comparing": "Bikwiye kugereranywa",
    "Prediction unavailable": "Iteganya ntiriboneka",
}


def _localize_opportunity_type(opportunity_type: str, locale: str | None) -> str:
    """Translate an opportunity-type label to Kinyarwanda when the locale asks for it."""
    if not _is_kinyarwanda(locale):
        return opportunity_type
    return _OPPORTUNITY_TYPE_RW.get(opportunity_type, opportunity_type)


def _risk_notes(gap_score: float, competition: float, confidence: float, access: float, locale: str | None = None) -> list[str]:
    """gap_score is a gap percentile within category (0-100, higher = more
    underserved relative to peers), not a general-purpose quality score."""
    rw = _is_kinyarwanda(locale)
    notes = []
    if confidence < 55:
        notes.append("Icyizere cy'amakuru ni hagati; emeza abandi bacuruza batemewe n'uko abakiriya banyura." if rw else "Data confidence is moderate; this may be a thin-data area, so validate informal competitors and customer flow in person.")
    if access < 45:
        notes.append("Kugerwaho ni intege nke ugereranyije n'ahandi hantu." if rw else "Accessibility (transport, roads) is weaker here than in most other areas.")
    if gap_score < 25:
        notes.append("Ibiboneka biri hafi bisa n'ibihagije cyangwa birenze icyo ibimenyetso by'agace byari biteganya." if rw else "Observed supply here already meets or exceeds what area fundamentals would predict - this looks saturated, not underserved.")
    notes.append("OSM ntabwo yandika neza ubucuruzi butemewe; iki gitekerezo gishobora kutagaragaza ibiboneka nyabyo." if rw else "OSM undercounts informal businesses, so the observed count here is a floor, not a ceiling - always verify on the ground.")
    return notes


def _recommendation(gap_score: float, confidence: float, competition_pressure: float, expected_count: float | None, observed_count: float, locale: str | None = None) -> str:
    """gap_score is a gap percentile within category (0-100, higher = more underserved)."""
    rw = _is_kinyarwanda(locale)
    if confidence < 45:
        return "Koresha iki nk'ikimenyetso cyo gushakisha hanyuma wemeze aha hantu ku rubuga mbere yo gufata icyemezo." if rw else "Data confidence here is limited - use this as an exploratory signal and validate the area physically before deciding."
    expected_txt = f"{expected_count:.1f}" if expected_count is not None else "?"
    if gap_score >= 80:
        return (f"Aha hantu hasa n'aho hatarigera hagerwaho bihagije: iteganya ni {expected_txt}, ariko {observed_count:.0f} ni byo biboneka ubu. Tangira isuzuma ku rubuga ku byerekeye ikodesha n'abandi bacuruza batemewe." if rw
                else f"This area looks underserved: fundamentals predict about {expected_txt}, but only {observed_count:.0f} are observed nearby. Prioritize field checks for rent, frontage and informal competitors before committing.")
    if gap_score >= 55:
        return (f"Hakiri umwanya wo gukura ugereranyije n'ibindi bice by'ubwoko bumwe. Gereranya n'andi mahitamo mbere yo kwiyemeza." if rw
                else "Some room to grow relative to other areas for this category. Worth comparing with a couple of alternatives before committing.")
    if gap_score >= 25:
        return ("Ibiboneka n'ubukenewe bingana muri iki gice. Kwitandukanya aho gutanga ibisanzwe bishobora gukenewe kugira ngo wihagararaho." if rw
                else "Supply and demand look roughly balanced here. Differentiation may matter more than location alone to stand out.")
    return (f"Aha hantu hasa n'ahuzuye: {observed_count:.0f} biraboneka ubu, hejuru y'icyo ibimenyetso by'agace byari biteganya ({expected_txt}). Shakisha ahandi hantu hafite ibiboneka bike ugereranyije n'ubukenewe." if rw
            else f"This area looks saturated: {observed_count:.0f} are already observed nearby, above what fundamentals would predict ({expected_txt}). Look for areas with less supply relative to demand.")
