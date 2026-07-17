from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import text

from app.db.session import get_db
from app.core.categories import normalise_category
from app.services.ml_opportunity_service import assess_location_ml, _localize_opportunity_type, list_nearby_competitors
from app.services.opportunity_service import list_opportunity_cells, summarize_opportunity_map
from app.services.geography_service import get_village_boundary
from app.services.location_labels import location_label

router = APIRouter()


def _map_quality_available(db: Session) -> bool:
    """True when the optional ml.map_quality_flags screening table exists."""
    try:
        return bool(db.execute(text("SELECT to_regclass('ml.map_quality_flags') IS NOT NULL")).scalar())
    except Exception:
        db.rollback()
        return False


@router.get('/opportunity-cells')
def opportunity_cells(
    category: str = Query('pharmacy'),
    district: str | None = None,
    sector: str | None = None,
    cell: str | None = None,
    limit: int = Query(60, ge=1, le=500),
    locale: str | None = Query(None),
    db: Session = Depends(get_db),
) -> dict:
    """List opportunity cells for a category, optionally filtered by district/sector/cell."""
    category = normalise_category(category)
    cells = list_opportunity_cells(db, category=category, district=district, sector=sector, cell=cell, limit=limit, locale=locale)
    return {'category': category, 'district': district, 'sector': sector, 'cell': cell, 'cells': cells, 'summary': summarize_opportunity_map(cells)}


@router.get('/opportunity-geojson')
def opportunity_geojson(
    category: str = Query('pharmacy'),
    layer: str = Query('opportunity'),
    limit: int = Query(2500, ge=1, le=10000),
    include_review: bool = Query(True),
    include_excluded: bool = Query(False),
    locale: str | None = Query(None),
    db: Session = Depends(get_db),
) -> dict:
    """Return map cells for the public opportunity map.

    Phase 36: if ml.map_quality_flags exists, obvious non-candidate areas
    such as water-heavy cells are excluded by default. Review cells can remain
    visible unless include_review=false.
    """
    category = normalise_category(category)
    try:
        import json

        # The map now has a single opportunity (gap) layer; the old per-composite
        # lenses were removed along with the composite scores.
        value_expr = 'opportunity_score'

        quality_available = _map_quality_available(db)
        quality_join = """
            LEFT JOIN ml.map_quality_flags q ON q.grid_id = p.grid_id
        """ if quality_available else """
            LEFT JOIN LATERAL (
              SELECT NULL::text AS candidate_status,
                     NULL::double precision AS water_overlap_pct,
                     NULL::integer AS poi_count_500,
                     NULL::integer AS building_count_300,
                     NULL::integer AS road_count_300,
                     '[]'::jsonb AS warning_labels
            ) q ON TRUE
        """
        quality_filter = "" if include_excluded else "AND COALESCE(q.candidate_status, 'candidate') <> 'excluded_water'"
        if not include_review:
            quality_filter += " AND COALESCE(q.candidate_status, 'candidate') = 'candidate'"

        rows = db.execute(text(f"""
            SELECT p.grid_id, p.opportunity_score, p.opportunity_score AS gap_score,
                   p.opportunity_type, p.zone_key, p.risk_level, p.district, p.sector, p.cell, g.village, p.explanation,
                   q.candidate_status, q.water_overlap_pct, q.poi_count_500,
                   q.building_count_300, q.road_count_300, q.warning_labels AS qa_warning_labels,
                   {value_expr} AS layer_value,
                   ST_AsGeoJSON(COALESCE(p.cell_geom, ST_Buffer(p.geom::geography, 350)::geometry)) AS geometry
            FROM ml.ml_opportunity_predictions p
            LEFT JOIN geo.analysis_grid g ON g.grid_id = p.grid_id
            {quality_join}
            WHERE p.business_category = :category
              {quality_filter}
            ORDER BY p.opportunity_score DESC
            LIMIT :limit
        """), {'category': category, 'limit': limit}).mappings().all()
        if rows:
            def _feature_properties(r):
                """Serialize one map cell's DB row into GeoJSON feature properties, localizing the opportunity type and adding a location label."""
                props = {k: (dict(v) if hasattr(v, 'keys') else v) for k, v in dict(r).items() if k != 'geometry'}
                if props.get('opportunity_type'):
                    props['opportunity_type'] = _localize_opportunity_type(props['opportunity_type'], locale)
                props['location_label'] = location_label(props.get('district'), props.get('sector'), props.get('cell'), props.get('village'), locale)
                return props

            return {
                'type': 'FeatureCollection',
                'features': [{
                    'type': 'Feature',
                    'geometry': json.loads(r['geometry']),
                    'properties': _feature_properties(r),
                } for r in rows],
                'metadata': {
                    'category': category,
                    'layer': layer,
                    'quality_screen': 'active' if quality_available else 'not_configured',
                    'include_review': include_review,
                    'include_excluded': include_excluded,
                    'returned_features': len(rows),
                },
            }
    except Exception:
        db.rollback()
    return {"type": "FeatureCollection", "features": [], "metadata": {"category": category, "layer": layer, "quality_screen": "unavailable", "returned_features": 0}}


@router.get('/map-quality-summary')
def map_quality_summary(db: Session = Depends(get_db)) -> dict:
    """Admin/developer diagnostic summary for the map-quality mask."""
    try:
        if not _map_quality_available(db):
            return {
                "status": "not_configured",
                "message": "Run scripts/audit_map_quality.py to create the map quality layer.",
                "summary": [],
            }
        summary = db.execute(text("""
            SELECT candidate_status, COUNT(*) AS count,
                   ROUND(AVG(water_overlap_pct)::numeric, 2) AS avg_water_overlap_pct,
                   ROUND(AVG(poi_count_500)::numeric, 2) AS avg_poi_count_500,
                   ROUND(AVG(building_count_300)::numeric, 2) AS avg_building_count_300,
                   ROUND(AVG(road_count_300)::numeric, 2) AS avg_road_count_300
            FROM ml.map_quality_flags
            GROUP BY candidate_status
            ORDER BY candidate_status
        """)).mappings().all()
        examples = db.execute(text("""
            SELECT q.grid_id, g.district, g.sector, g.cell, q.candidate_status,
                   q.water_overlap_pct, q.poi_count_500, q.building_count_300, q.road_count_300,
                   q.warning_labels
            FROM ml.map_quality_flags q
            JOIN geo.analysis_grid g ON g.grid_id = q.grid_id
            WHERE q.candidate_status <> 'candidate'
            ORDER BY q.water_overlap_pct DESC, q.poi_count_500 ASC
            LIMIT 25
        """)).mappings().all()
        return {
            "status": "ready",
            "summary": [dict(r) for r in summary],
            "review_examples": [dict(r) for r in examples],
        }
    except Exception as exc:
        db.rollback()
        return {"status": "error", "message": str(exc), "summary": [], "review_examples": []}


@router.post('/assess')
def assess(payload: dict, db: Session = Depends(get_db)) -> dict:
    """Assess a point for a category (nearest scored cell + live competitor recount)."""
    return assess_location_ml(
        db,
        latitude=float(payload.get('latitude')),
        longitude=float(payload.get('longitude')),
        business_category=normalise_category(payload.get('business_category') or payload.get('category') or 'pharmacy'),
        radius_meters=int(payload.get('radius_meters') or 500),
        locale=payload.get('locale'),
    )


@router.get('/nearby-competitors')
def nearby_competitors(
    latitude: float, longitude: float, category: str = Query('pharmacy'),
    radius_meters: int = Query(1000, ge=100, le=3000), limit: int = Query(40, ge=1, le=100),
    db: Session = Depends(get_db),
) -> dict:
    """List individual competitor points (name + position) around a location."""
    category = normalise_category(category)
    competitors = list_nearby_competitors(db, latitude, longitude, category, radius_meters, limit)
    return {"business_category": category, "latitude": latitude, "longitude": longitude, "competitors": competitors}


@router.get('/village-boundary')
def village_boundary(latitude: float, longitude: float, db: Session = Depends(get_db)) -> dict:
    """Return the administrative area (district/sector/cell/village) and its outline at a point."""
    import json

    boundary = get_village_boundary(db, latitude, longitude)
    if boundary:
        return {
            "district": boundary.get("district"),
            "sector": boundary.get("sector"),
            "cell": boundary.get("cell"),
            "village": boundary.get("village"),
            "geometry": json.loads(boundary["geometry"]) if boundary.get("geometry") else None,
        }
    return {"district": None, "sector": None, "cell": None, "village": None, "geometry": None}


@router.get('/area-preview')
def area_preview(latitude: float, longitude: float, category: str = Query('pharmacy'), db: Session = Depends(get_db)) -> dict:
    """Lightweight single-point assessment used for map hover/preview."""
    category = normalise_category(category)
    assessment = assess_location_ml(db, latitude=latitude, longitude=longitude, business_category=category, radius_meters=500)
    return {'category': category, 'location': assessment, 'source': assessment.get('source')}


@router.get('/best-business')
def best_business(latitude: float, longitude: float, db: Session = Depends(get_db)) -> dict:
    """Rank active business categories for the nearest grid cell."""
    try:
        rows = db.execute(text("""
            WITH nearest AS (
              SELECT grid_id
              FROM ml.ml_opportunity_predictions
              ORDER BY geom <-> ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)
              LIMIT 1
            )
            SELECT p.business_category, p.opportunity_score,
                   p.opportunity_type, p.explanation
            FROM ml.ml_opportunity_predictions p
            JOIN nearest n ON n.grid_id = p.grid_id
            ORDER BY p.opportunity_score DESC
        """), {"lon": longitude, "lat": latitude}).mappings().all()
        if rows:
            return {"latitude": latitude, "longitude": longitude, "ranked_categories": [dict(r) for r in rows]}
    except Exception:
        db.rollback()
    return {"latitude": latitude, "longitude": longitude, "ranked_categories": []}


@router.get('/competition-analysis')
def competition_analysis(latitude: float, longitude: float, category: str = Query('pharmacy'), db: Session = Depends(get_db)) -> dict:
    """Competitor counts by radius plus nearby complementary/demand-generating POIs."""
    category = normalise_category(category)
    try:
        row = db.execute(text("""
            SELECT
              COUNT(*) FILTER (WHERE ST_DWithin(geom::geography, ST_SetSRID(ST_MakePoint(:lon,:lat),4326)::geography, 300)) AS within_300m,
              COUNT(*) FILTER (WHERE ST_DWithin(geom::geography, ST_SetSRID(ST_MakePoint(:lon,:lat),4326)::geography, 500)) AS within_500m,
              COUNT(*) FILTER (WHERE ST_DWithin(geom::geography, ST_SetSRID(ST_MakePoint(:lon,:lat),4326)::geography, 1000)) AS within_1000m,
              MIN(ST_Distance(geom::geography, ST_SetSRID(ST_MakePoint(:lon,:lat),4326)::geography)) AS nearest_competitor_m
            FROM curated.osm_poi_features
            WHERE category_key = :category
        """), {"lon": longitude, "lat": latitude, "category": category}).mappings().first()
        complement = db.execute(text("""
            SELECT category_key, COUNT(*) AS count
            FROM curated.osm_poi_features
            WHERE category_key <> :category
              AND category_key IN ('pharmacy','restaurant','cafe','grocery','salon','market','school','health','transport','finance')
              AND ST_DWithin(geom::geography, ST_SetSRID(ST_MakePoint(:lon,:lat),4326)::geography, 1000)
            GROUP BY category_key ORDER BY count DESC
        """), {"lon": longitude, "lat": latitude, "category": category}).mappings().all()
        return {
            "business_category": category,
            "latitude": latitude,
            "longitude": longitude,
            "competitors": dict(row or {}),
            "nearby_complementary_and_demand_generators": [dict(r) for r in complement],
        }
    except Exception:
        db.rollback()
        return {"business_category": category, "latitude": latitude, "longitude": longitude, "competitors": {}, "nearby_complementary_and_demand_generators": []}
