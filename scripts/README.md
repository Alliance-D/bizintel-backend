# Data scripts

Import, feature-generation, and ML pipeline scripts. The database schema
itself is created by Alembic (`alembic upgrade head`), not by any script
here - run that first.

Recommended sequence, from `backend/` with `DATABASE_URL` set:

1. `alembic upgrade head` - create the schema (`raw`/`geo`/`curated`/`ml`/`app`/`field`/`meta`).
2. `import_admin_boundaries.py` - import district/sector boundary geometries.
3. `generate_analysis_grid.py` - generate the `geo.analysis_grid` hex grid for Kigali.
4. `import_osm_business_features.py` - import OSM POIs into `curated.osm_poi_features`.
5. `import_population_density.py` - import population density CSV into `curated.population_density_points`.
6. `import_population_count.py` - import sector population counts into `curated.population_count_features`.
7. `import_establishment_census.py` - aggregate the NISR Establishment Census into `curated.establishment_area_features`.
8. `import_population_welfare.py` - aggregate PHC5 census microdata into sector-level `curated.population_welfare_features`.
9. `import_district_socioeconomic.py` - aggregate LFS + VUP welfare survey microdata into district-level `curated.population_welfare_features`.
10. `build_grid_category_features.py` - build `ml.grid_category_features` (grid-cell + category rows), joining in all of the above.
11. `train_and_score_opportunity_model.py` - train and score the opportunity model.
12. `audit_map_quality.py` - flag low-quality/non-candidate map cells in `ml.map_quality_flags`.

Steps 7-9 read restricted microdata from outside this repository (see
`backend/README.md` for paths and licensing notes) and only ever write
aggregated, non-identifying counts into the database.
