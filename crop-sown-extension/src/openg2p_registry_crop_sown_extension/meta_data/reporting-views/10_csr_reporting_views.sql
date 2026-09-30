-- Crop Sown Registry reporting views, for Superset / G2P Insights and SQL users.
--
-- They read the crop-season projection (g2p_activity_projection_crop_sown): one
-- row per crop season, kept current by the platform in the same transaction as
-- every activity. So these are plain views, always up to date, with no refresh
-- job. Geography comes from the crop season's location (geo_dimensions: the
-- plot's woreda and the region/zone above it, as named Master Data levels).
--
-- Re-run on every install/upgrade by db-seed (CREATE OR REPLACE). Hand-written,
-- not generated.

-- One row per crop season, with its location flattened to columns.
CREATE OR REPLACE VIEW csr_rpt_crop_season AS
SELECT
    p.context_id                              AS crop_season_id,
    p.context_key,
    p.crop_year,
    p.season,
    p.crop,
    p.variety,
    p.plot_id,
    p.farmer_id,
    p.fayda_fan,
    p.stage,
    p.planned_area_ha,
    p.area_sown_ha,
    p.sowing_date,
    p.seed_type,
    p.sowing_verified,
    p.latest_growth_stage,
    p.latest_crop_condition,
    p.infestation_count,
    p.max_infestation_severity,
    p.damage_count,
    p.max_loss_percent,
    p.area_harvested_ha,
    p.quantity_harvested_qt,
    p.yield_qt_per_ha,
    p.harvest_date,
    p.cluster_id,
    p.context_status,
    p.last_occurred_at,
    p.geo_dimensions -> 'region' ->> 'code'   AS region_code,
    p.geo_dimensions -> 'region' ->> 'name'   AS region_name,
    p.geo_dimensions -> 'zone' ->> 'code'     AS zone_code,
    p.geo_dimensions -> 'zone' ->> 'name'     AS zone_name,
    p.geo_dimensions -> 'woreda' ->> 'code'   AS woreda_code,
    p.geo_dimensions -> 'woreda' ->> 'name'   AS woreda_name
FROM g2p_activity_projection_crop_sown p;

-- Crop performance at each level: crop seasons, farmers, plots, areas,
-- production and yield (production over harvested area) per crop year, season
-- and crop. Crop seasons without a location appear under a NULL level.
CREATE OR REPLACE VIEW csr_rpt_crop_performance_region AS
SELECT
    crop_year, season, region_code, region_name, crop,
    count(*)                                                        AS crop_seasons,
    count(DISTINCT farmer_id)                                       AS farmers,
    count(DISTINCT plot_id)                                         AS plots,
    coalesce(sum(planned_area_ha), 0)                               AS planned_area_ha,
    coalesce(sum(area_sown_ha), 0)                                  AS area_sown_ha,
    coalesce(sum(area_harvested_ha), 0)                             AS area_harvested_ha,
    coalesce(sum(quantity_harvested_qt), 0)                         AS production_qt,
    round(sum(quantity_harvested_qt) / nullif(sum(area_harvested_ha), 0), 3) AS yield_qt_per_ha,
    count(*) FILTER (WHERE infestation_count > 0)                   AS crop_seasons_infested,
    count(*) FILTER (WHERE damage_count > 0)                        AS crop_seasons_damaged
FROM csr_rpt_crop_season
GROUP BY crop_year, season, region_code, region_name, crop;

CREATE OR REPLACE VIEW csr_rpt_crop_performance_zone AS
SELECT
    crop_year, season, region_code, region_name, zone_code, zone_name, crop,
    count(*)                                                        AS crop_seasons,
    count(DISTINCT farmer_id)                                       AS farmers,
    count(DISTINCT plot_id)                                         AS plots,
    coalesce(sum(planned_area_ha), 0)                               AS planned_area_ha,
    coalesce(sum(area_sown_ha), 0)                                  AS area_sown_ha,
    coalesce(sum(area_harvested_ha), 0)                             AS area_harvested_ha,
    coalesce(sum(quantity_harvested_qt), 0)                         AS production_qt,
    round(sum(quantity_harvested_qt) / nullif(sum(area_harvested_ha), 0), 3) AS yield_qt_per_ha,
    count(*) FILTER (WHERE infestation_count > 0)                   AS crop_seasons_infested,
    count(*) FILTER (WHERE damage_count > 0)                        AS crop_seasons_damaged
FROM csr_rpt_crop_season
GROUP BY crop_year, season, region_code, region_name, zone_code, zone_name, crop;

CREATE OR REPLACE VIEW csr_rpt_crop_performance_woreda AS
SELECT
    crop_year, season, region_code, region_name, zone_code, zone_name, woreda_code, woreda_name, crop,
    count(*)                                                        AS crop_seasons,
    count(DISTINCT farmer_id)                                       AS farmers,
    count(DISTINCT plot_id)                                         AS plots,
    coalesce(sum(planned_area_ha), 0)                               AS planned_area_ha,
    coalesce(sum(area_sown_ha), 0)                                  AS area_sown_ha,
    coalesce(sum(area_harvested_ha), 0)                             AS area_harvested_ha,
    coalesce(sum(quantity_harvested_qt), 0)                         AS production_qt,
    round(sum(quantity_harvested_qt) / nullif(sum(area_harvested_ha), 0), 3) AS yield_qt_per_ha,
    count(*) FILTER (WHERE infestation_count > 0)                   AS crop_seasons_infested,
    count(*) FILTER (WHERE damage_count > 0)                        AS crop_seasons_damaged
FROM csr_rpt_crop_season
GROUP BY crop_year, season, region_code, region_name, zone_code, zone_name, woreda_code, woreda_name, crop;
