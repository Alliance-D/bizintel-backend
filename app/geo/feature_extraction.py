from dataclasses import dataclass
from sqlalchemy import text
from sqlalchemy.orm import Session


@dataclass
class LocationFeatures:
    demand_score: float
    accessibility_score: float
    competition_pressure: float
    commercial_activity_score: float
    risk_score: float
    confidence_score: float
    population_density_500m: float = 0.0
    population_density_1000m: float = 0.0
    commercial_poi_count_500m: int = 0
    competitor_count_300m: int = 0
    competitor_count_500m: int = 0
    competitor_count_1000m: int = 0
    market_distance_m: float = 9999.0
    nearest_main_road_m: float = 9999.0
    bus_stop_count_500m: int = 0


def _normalise(value: float, max_value: float) -> float:
    if value is None:
        return 0.0
    return round(max(0.0, min(100.0, (float(value) / max_value) * 100.0)), 2)


def _score_from_distance(distance_m: float | None, ideal_m: float = 150.0, bad_m: float = 1500.0) -> float:
    if distance_m is None:
        return 0.0
    if distance_m <= ideal_m:
        return 100.0
    if distance_m >= bad_m:
        return 0.0
    return round(100.0 * (1.0 - ((float(distance_m) - ideal_m) / (bad_m - ideal_m))), 2)


def _fallback_features(latitude: float, longitude: float, business_category: str) -> LocationFeatures:
    # Uses the shared product-grade demo intelligence layer. This keeps the
    # frontend and backend consistent before all real data imports/models exist.
    from app.services.demo_data import features_from_zone

    return features_from_zone(latitude, longitude, business_category)


def extract_location_features(
    db: Session,
    latitude: float,
    longitude: float,
    business_category: str,
    radius_meters: int,
) -> LocationFeatures:
    """Extract spatial features for one location.

    Phase 2 tries to use PostGIS data warehouse tables. If the tables/functions
    are not installed or have not been imported yet, it falls back to stable demo
    values so the API remains usable.
    """
    try:
        row = db.execute(
            text("""
                SELECT * FROM ml.extract_location_features_sql(
                    :lat, :lon, :category, :radius
                )
            """),
            {"lat": latitude, "lon": longitude, "category": business_category, "radius": radius_meters},
        ).mappings().first()
    except Exception:
        return _fallback_features(latitude, longitude, business_category)

    if not row:
        return _fallback_features(latitude, longitude, business_category)

    pop500 = float(row.get("population_density_500m") or 0)
    pop1000 = float(row.get("population_density_1000m") or 0)
    commercial_count = int(row.get("commercial_poi_count_500m") or 0)
    comp300 = int(row.get("competitor_count_300m") or 0)
    comp500 = int(row.get("competitor_count_500m") or 0)
    comp1000 = int(row.get("competitor_count_1000m") or 0)
    market_dist = float(row.get("market_distance_m") or 9999)
    road_dist = float(row.get("nearest_main_road_m") or 9999)
    bus_count = int(row.get("bus_stop_count_500m") or 0)

    demand = _normalise(pop500, 10000)
    road_access = _score_from_distance(road_dist, ideal_m=80, bad_m=1600)
    bus_access = _normalise(bus_count, 6)
    market_access = _score_from_distance(market_dist, ideal_m=250, bad_m=2500)
    access = round((road_access * 0.45) + (bus_access * 0.30) + (market_access * 0.25), 2)
    commercial = _normalise(commercial_count, 30)
    competition = _normalise(comp500, 15)
    risk = round(max(0, min(100, (competition * 0.65) + ((100 - access) * 0.25) + ((100 - demand) * 0.10))), 2)

    populated_layers = sum([
        pop500 > 0,
        commercial_count > 0,
        road_dist < 9999,
        market_dist < 9999,
        bus_count > 0,
    ])
    confidence = round(min(95, 35 + populated_layers * 12), 2)

    return LocationFeatures(
        demand_score=demand,
        accessibility_score=access,
        competition_pressure=competition,
        commercial_activity_score=commercial,
        risk_score=risk,
        confidence_score=confidence,
        population_density_500m=pop500,
        population_density_1000m=pop1000,
        commercial_poi_count_500m=commercial_count,
        competitor_count_300m=comp300,
        competitor_count_500m=comp500,
        competitor_count_1000m=comp1000,
        market_distance_m=market_dist,
        nearest_main_road_m=road_dist,
        bus_stop_count_500m=bus_count,
    )
