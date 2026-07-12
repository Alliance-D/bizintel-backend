"""Boundary tests for the gap-band classifier shared by the scoring pipeline,
the API and the tests. Every band edge is pinned so a stray ``>=`` -> ``>``
can never silently reshuffle how cells are labelled."""

import pytest

from app.services.gap_semantics import classify_gap_percentile


@pytest.mark.parametrize(
    "percentile, expected",
    [
        (100.0, ("Underserved", "underserved", "low")),
        (80.0, ("Underserved", "underserved", "low")),   # inclusive lower edge
        (79.999, ("Room to grow", "emerging", "medium")),
        (55.0, ("Room to grow", "emerging", "medium")),   # inclusive lower edge
        (54.999, ("Balanced", "balanced", "medium")),
        (25.0, ("Balanced", "balanced", "medium")),       # inclusive lower edge
        (24.999, ("Saturated", "saturated", "high")),
        (0.0, ("Saturated", "saturated", "high")),
    ],
)
def test_classify_gap_percentile_bands(percentile, expected):
    assert classify_gap_percentile(percentile) == expected


def test_label_zone_and_risk_are_internally_consistent():
    # The most underserved band is the lowest risk; the saturated band the
    # highest - the three returned values must always agree in direction.
    label_hi, zone_hi, risk_hi = classify_gap_percentile(95)
    label_lo, zone_lo, risk_lo = classify_gap_percentile(5)
    assert (label_hi, zone_hi, risk_hi) == ("Underserved", "underserved", "low")
    assert (label_lo, zone_lo, risk_lo) == ("Saturated", "saturated", "high")


def test_classification_is_monotonic_across_the_scale():
    # Walking the percentile up should never move a cell to a "worse" band.
    order = ["saturated", "balanced", "emerging", "underserved"]
    seen = [classify_gap_percentile(p)[1] for p in range(0, 101, 5)]
    ranks = [order.index(z) for z in seen]
    assert ranks == sorted(ranks)
