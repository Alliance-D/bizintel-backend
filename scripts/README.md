# Data scripts

This folder will contain import and feature-generation scripts.

Recommended sequence:

1. Import boundaries into `geo.*` tables.
2. Import population density CSV into `geo.population_density_grid`.
3. Import OSM extracts into `geo.osm_roads`, `geo.osm_pois`, `geo.osm_buildings`.
4. Aggregate survey/census data into `curated.*` feature tables.
5. Generate `geo.analysis_grid` for Kigali.
6. Generate `ml.training_features` as grid-cell + category rows.
7. Train and register ML models.
