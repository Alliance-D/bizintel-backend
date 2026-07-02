# Data scripts

Import, feature-generation, and ML pipeline scripts.

Recommended sequence:

1. `bootstrap_data_layer.py` - create the `curated.*`/`geo.*`/`ml.*` PostGIS data layer.
2. `import_admin_boundaries.py` - import district/sector boundary geometries.
3. `generate_analysis_grid.py` - generate the `geo.analysis_grid` hex grid for Kigali.
4. `import_osm_business_features.py` - import OSM POIs into `curated.osm_poi_features`.
5. `import_population_density.py` - import population density CSV into `curated.population_density_points`.
6. `import_population_count.py` - import sector population counts into `curated.population_count_features`.
7. `build_grid_category_features.py` - build `ml.grid_category_features` (grid-cell + category rows).
8. `train_and_score_opportunity_model.py` - train and score the opportunity model.
9. `audit_map_quality.py` - flag low-quality/non-candidate map cells in `ml.map_quality_flags`.
