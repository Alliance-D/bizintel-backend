-- Phase 2: SQL helper functions for spatial feature extraction.

CREATE OR REPLACE FUNCTION geo.point_4326(p_lon DOUBLE PRECISION, p_lat DOUBLE PRECISION)
RETURNS geometry(Point, 4326)
LANGUAGE SQL
IMMUTABLE
AS $$
    SELECT ST_SetSRID(ST_MakePoint(p_lon, p_lat), 4326);
$$;

CREATE OR REPLACE FUNCTION ml.extract_location_features_sql(
    p_lat DOUBLE PRECISION,
    p_lon DOUBLE PRECISION,
    p_business_category TEXT,
    p_radius_m INT DEFAULT 500
)
RETURNS TABLE (
    population_density_500m DOUBLE PRECISION,
    population_density_1000m DOUBLE PRECISION,
    commercial_poi_count_500m INT,
    competitor_count_300m INT,
    competitor_count_500m INT,
    competitor_count_1000m INT,
    market_distance_m DOUBLE PRECISION,
    nearest_main_road_m DOUBLE PRECISION,
    bus_stop_count_500m INT
)
LANGUAGE SQL
STABLE
AS $$
WITH pt AS (
    SELECT geo.point_4326(p_lon, p_lat) AS geom
), poi AS (
    SELECT
        COUNT(*) FILTER (
            WHERE ST_DWithin(p.geom::geography, pt.geom::geography, 500)
              AND p.category IN ('commercial','food','finance','education','health','market','retail')
        )::INT AS commercial_poi_count_500m,
        COUNT(*) FILTER (
            WHERE ST_DWithin(p.geom::geography, pt.geom::geography, 300)
              AND p.category = p_business_category
        )::INT AS competitor_count_300m,
        COUNT(*) FILTER (
            WHERE ST_DWithin(p.geom::geography, pt.geom::geography, 500)
              AND p.category = p_business_category
        )::INT AS competitor_count_500m,
        COUNT(*) FILTER (
            WHERE ST_DWithin(p.geom::geography, pt.geom::geography, 1000)
              AND p.category = p_business_category
        )::INT AS competitor_count_1000m,
        MIN(ST_Distance(p.geom::geography, pt.geom::geography)) FILTER (
            WHERE p.category = 'market'
        ) AS market_distance_m,
        COUNT(*) FILTER (
            WHERE ST_DWithin(p.geom::geography, pt.geom::geography, 500)
              AND p.subcategory IN ('bus_stop','transport_stop','taxi_stand')
        )::INT AS bus_stop_count_500m
    FROM geo.osm_pois p, pt
), pop AS (
    SELECT
        AVG(density) FILTER (WHERE ST_DWithin(g.geom::geography, pt.geom::geography, 500)) AS population_density_500m,
        AVG(density) FILTER (WHERE ST_DWithin(g.geom::geography, pt.geom::geography, 1000)) AS population_density_1000m
    FROM geo.population_density_grid g, pt
), roads AS (
    SELECT MIN(ST_Distance(r.geom::geography, pt.geom::geography)) AS nearest_main_road_m
    FROM geo.osm_roads r, pt
    WHERE r.road_class IN ('motorway','trunk','primary','secondary','tertiary')
)
SELECT
    COALESCE(pop.population_density_500m, 0),
    COALESCE(pop.population_density_1000m, 0),
    COALESCE(poi.commercial_poi_count_500m, 0),
    COALESCE(poi.competitor_count_300m, 0),
    COALESCE(poi.competitor_count_500m, 0),
    COALESCE(poi.competitor_count_1000m, 0),
    COALESCE(poi.market_distance_m, 9999),
    COALESCE(roads.nearest_main_road_m, 9999),
    COALESCE(poi.bus_stop_count_500m, 0)
FROM pop, poi, roads;
$$;

CREATE OR REPLACE FUNCTION geo.generate_analysis_grid_bbox(
    min_lon DOUBLE PRECISION,
    min_lat DOUBLE PRECISION,
    max_lon DOUBLE PRECISION,
    max_lat DOUBLE PRECISION,
    grid_size_m INT DEFAULT 250
)
RETURNS INT
LANGUAGE plpgsql
AS $$
DECLARE
    inserted_count INT;
BEGIN
    INSERT INTO geo.analysis_grid (grid_id, grid_size_m, geom)
    SELECT
        'grid_' || grid_size_m || '_' || row_number() OVER () AS grid_id,
        grid_size_m,
        ST_Transform(cell.geom, 4326)::geometry(Polygon,4326)
    FROM ST_SquareGrid(
        grid_size_m,
        ST_Transform(ST_MakeEnvelope(min_lon, min_lat, max_lon, max_lat, 4326), 3857)
    ) AS cell
    ON CONFLICT (grid_id) DO NOTHING;

    GET DIAGNOSTICS inserted_count = ROW_COUNT;
    RETURN inserted_count;
END;
$$;
