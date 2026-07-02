from dataclasses import dataclass


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
