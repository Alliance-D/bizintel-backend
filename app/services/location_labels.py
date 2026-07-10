"""Turns a grid cell's raw district/sector/cell/village fields into a
human-readable location name for reports, instead of exposing a raw grid_id.
Falls back gracefully as fields go missing: village -> cell -> sector -> district.
"""
from __future__ import annotations


def _is_rw(locale: str | None) -> bool:
    return (locale or "").lower().startswith(("rw", "kin"))


def location_label(
    district: str | None,
    sector: str | None,
    cell: str | None,
    village: str | None,
    locale: str | None = None,
) -> str:
    rw = _is_rw(locale)

    if village and sector:
        return f"aho hafi y'umudugudu wa {village}, mu Murenge wa {sector}" if rw \
            else f"the part of {sector} around {village} village"
    if village and district:
        return f"aho hafi y'umudugudu wa {village}, mu Karere ka {district}" if rw \
            else f"the part of {district} around {village} village"
    if village:
        return f"hafi y'umudugudu wa {village}" if rw else f"near {village} village"
    if cell and sector:
        return f"Akagari ka {cell}, Umurenge wa {sector}" if rw else f"{cell}, {sector} sector"
    if sector and district:
        return f"Umurenge wa {sector}, Akarere ka {district}" if rw else f"{sector} sector, {district} district"
    if sector:
        return f"Umurenge wa {sector}" if rw else f"{sector} sector"
    if district:
        return f"Akarere ka {district}" if rw else f"{district} district"
    return "Kigali"
