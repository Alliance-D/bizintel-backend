from app.services.expansion_planner_service import meters_between, plan_expansion


def test_meters_between_same_point_is_zero():
    assert meters_between(-1.95, 30.05, -1.95, 30.05) == 0


def test_meters_between_known_kigali_scale_distance():
    # Two points roughly 1.5km apart in Kigali - sanity-checks the
    # equirectangular approximation is in the right ballpark, not exact.
    distance = meters_between(-1.95, 30.05, -1.96, 30.06)
    assert 1000 < distance < 2200


class _FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def mappings(self):
        return self

    def all(self):
        return self._rows


class _FakeSession:
    """Returns a fixed set of candidate grid cells instead of hitting a real database."""

    def __init__(self, rows):
        self._rows = rows

    def execute(self, *_args, **_kwargs):
        return _FakeResult(self._rows)


def _candidate(grid_id, lat, lon, score):
    return {
        "grid_id": grid_id, "latitude": lat, "longitude": lon,
        "opportunity_score": score, "demand_score": score, "accessibility_score": score,
        "commercial_activity_score": score, "competition_pressure": 50, "confidence_score": 80,
        "opportunity_type": "Strong opportunity", "risk_level": "low",
        "district": "Gasabo", "sector": "Kimironko",
    }


def test_plan_expansion_excludes_cells_too_close_to_existing_location():
    existing = [{"latitude": -1.9500, "longitude": 30.0900}]
    # One candidate right on top of the existing location, one far away.
    candidates = [
        _candidate("near", -1.9500, 30.0900, 90),
        _candidate("far", -1.9700, 30.1200, 85),
    ]
    result = plan_expansion(_FakeSession(candidates), "salon", existing, limit=8, min_distance_from_existing_m=600)
    grid_ids = [c["grid_id"] for c in result["candidates"]]
    assert "near" not in grid_ids
    assert "far" in grid_ids
    assert result["excluded_near_existing"] == 1


def test_plan_expansion_spaces_out_candidates_from_each_other():
    existing = []
    # Two candidates ~50m apart (well under the 400m default spacing) plus one far away.
    candidates = [
        _candidate("peak", -1.9500, 30.0900, 95),
        _candidate("shoulder", -1.9504, 30.0900, 94),  # ~45m from "peak"
        _candidate("elsewhere", -1.9800, 30.1300, 80),
    ]
    result = plan_expansion(_FakeSession(candidates), "salon", existing, limit=8)
    grid_ids = [c["grid_id"] for c in result["candidates"]]
    assert "peak" in grid_ids
    assert "shoulder" not in grid_ids  # too close to the higher-scored "peak"
    assert "elsewhere" in grid_ids


def test_plan_expansion_handles_no_candidates_gracefully():
    result = plan_expansion(_FakeSession([]), "salon", [], limit=8)
    assert result["candidates"] == []
