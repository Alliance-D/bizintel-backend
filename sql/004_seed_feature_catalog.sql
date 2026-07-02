INSERT INTO meta.feature_catalog (
    feature_name, feature_group, source_layer, geographic_level, business_category_specific,
    calculation_method, interpretation, quality_risk
) VALUES
('population_density_500m','Demand','geo.population_density_grid','grid/candidate location',false,'Average raster density points within 500m of candidate centroid.','Fine-scale residential demand around the location.','Raster year and resolution may not capture daytime population.'),
('population_density_1000m','Demand','geo.population_density_grid','grid/candidate location',false,'Average raster density points within 1000m of candidate centroid.','Wider catchment residential demand.','May smooth local street-level variation.'),
('sector_population','Demand','curated.sector_population_features','sector',false,'Join candidate point to containing sector and attach latest sector population.','Area-level market size.','Sector can be too broad for exact location scoring.'),
('female_share','Demand','curated.sector_population_features','sector',false,'Female population / total population in sector.','Category-relevant demographic context for selected business types.','Use carefully; do not stereotype demand.'),
('youth_share','Demand','PHC5 aggregated features','sector/district',false,'Share of population in youth or working-age bands after aggregation.','Youth/customer profile context.','Requires clean age aggregation.'),
('income_proxy','Purchasing power','curated.district_lfs_features / VUP expenditure','district/sector',false,'Aggregate income/expenditure indicators.','Spending capacity proxy.','Survey-level aggregation may be coarse.'),
('welfare_index','Purchasing power','curated.welfare_area_features','district/sector',false,'Composite normalized welfare/quintile/service indicators.','Socio-economic affordability profile.','Avoid exposing household-level microdata.'),
('nearest_main_road_m','Accessibility','geo.osm_roads','candidate location',false,'Minimum distance to primary/secondary/tertiary road.','Road visibility and access.','OSM road completeness generally strong but verify classification.'),
('bus_stop_count_500m','Accessibility','geo.osm_pois / transport stops','candidate location',false,'Count transport stops within 500m.','Public transport accessibility.','Transport stop coverage may be incomplete.'),
('market_distance_m','Commercial activity','geo.osm_pois','candidate location',false,'Distance to nearest market POI.','Proximity to demand generator.','Markets may need official/manual enrichment.'),
('commercial_poi_count_500m','Commercial activity','geo.osm_pois','candidate location',false,'Count commercial/education/finance/food/health POIs within 500m.','General activity intensity around the location.','OSM POI coverage varies.'),
('competitor_count_300m','Competition','geo.osm_pois + establishment/field data','candidate location + category',true,'Count same-category business points within 300m.','Immediate competition pressure.','Exact informal competitor coverage may be incomplete.'),
('competitor_count_500m','Competition','geo.osm_pois + establishment/field data','candidate location + category',true,'Count same-category business points within 500m.','Neighborhood competition pressure.','Point-level business data may be missing.'),
('competitor_count_1000m','Competition','geo.osm_pois + establishment/field data','candidate location + category',true,'Count same-category business points within 1000m.','Wider saturation pressure.','May overstate competition if barriers/travel paths exist.'),
('business_density_area','Commercial environment','curated.establishment_area_features','sector/district/category',true,'Establishment count normalized by area/population.','Observed business activity intensity.','If no coordinates, only area-level not street-level.'),
('opportunity_gap_score','Opportunity','ml.training_features','grid/candidate/category',true,'Demand/access/commercial signal minus excessive same-category supply.','Core opportunity potential score.','Requires validation and category calibration.')
ON CONFLICT (feature_name) DO UPDATE SET
    feature_group = EXCLUDED.feature_group,
    source_layer = EXCLUDED.source_layer,
    geographic_level = EXCLUDED.geographic_level,
    business_category_specific = EXCLUDED.business_category_specific,
    calculation_method = EXCLUDED.calculation_method,
    interpretation = EXCLUDED.interpretation,
    quality_risk = EXCLUDED.quality_risk;
