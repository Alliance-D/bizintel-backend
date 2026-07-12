"""Turns a grid cell's raw district/sector/cell fields into a human-readable
location name for reports, instead of exposing a raw grid_id.

Labels are administrative and cell-based (cell within sector); villages are
deliberately not used - they're too granular to be a useful, recognisable
handle for a location in the report. Falls back gracefully as fields go
missing: cell -> sector -> district.
"""
from __future__ import annotations


def _is_rw(locale: str | None) -> bool:
    """True when the locale denotes Kinyarwanda."""
    return (locale or "").lower().startswith(("rw", "kin"))


def location_label(
    district: str | None,
    sector: str | None,
    cell: str | None,
    village: str | None = None,  # accepted for backward compat, intentionally unused
    locale: str | None = None,
) -> str:
    """Build a human-readable cell-and-sector label, de-duplicating repeated parts."""
    def norm(x: str | None) -> str:
        """Trim and lower-case a name part for comparison."""
        return (x or "").strip()

    d, s, c = norm(district), norm(sector), norm(cell)

    # Rwandan admin naming often repeats a name across levels (e.g. Kimironko
    # cell inside Kimironko sector) - collapse the repeat rather than say it twice.
    if c and s and c.lower() != s.lower():
        return f"{c}, {s}"
    if c:
        return c
    if s and d and s.lower() != d.lower():
        return f"{s}, {d}"
    if s:
        return s
    if d:
        return d
    return "Kigali"
