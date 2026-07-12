"""Gap-band semantics shared across the platform.

The offline scoring pipeline ranks every grid cell by the gap between the demand
its fundamentals predict and the businesses actually observed nearby, then turns
that rank into a band a person can read. Keeping the rule here - free of any
pandas/scikit/database dependency - lets the scoring script, the API and the
tests all agree on exactly where one band ends and the next begins.
"""

from __future__ import annotations


def classify_gap_percentile(gap_percentile: float) -> tuple[str, str, str]:
    """Map a within-category gap percentile to (label, zone_key, risk_level).

    ``gap_percentile`` is a row's rank (0-100) among the gap values of its own
    business category - relative, not an absolute magnitude, so it stays
    comparable across categories whose typical counts differ widely. A higher
    percentile means the location looks more underserved than its peers.
    """
    if gap_percentile >= 80:
        return "Underserved", "underserved", "low"
    if gap_percentile >= 55:
        return "Room to grow", "emerging", "medium"
    if gap_percentile >= 25:
        return "Balanced", "balanced", "medium"
    return "Saturated", "saturated", "high"
