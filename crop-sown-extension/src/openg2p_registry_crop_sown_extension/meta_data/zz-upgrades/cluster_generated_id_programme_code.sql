-- Upgrade: the Cluster ID is generated; the programme's cluster code moves to its own field.
--
-- Why this file exists
-- --------------------
-- Every other file under meta_data/ inserts with ON CONFLICT DO NOTHING, so on an
-- install that already holds the Cluster register's metadata the new values never
-- reach it; and the model migration creates missing tables but never adds a
-- column to an existing one. This file brings such an install to what a fresh
-- install gets. It sorts after every other directory (zz-), runs after the model
-- migration and the inserts, and before the sample loader. It is idempotent: on a
-- fresh install, or on a second run, every statement matches nothing.
--
-- Before: the Cluster's functional_record_id was the programme code, typed by
-- staff (e.g. CL-ET0406-001), and the ID generator was off.
-- After: functional_record_id is generated on approval (pool "cluster", e.g.
-- CL-4729318560) and the programme code is the optional programme_cluster_code.
--
-- What it does NOT touch: existing functional IDs. A cluster registered with a
-- typed code keeps it as its Cluster ID (activities enrol clusters by that ID);
-- the code is also copied into programme_cluster_code. Cluster history rows are
-- left as they were recorded.

-- 1. The new column, on the register, its history and its intake form tables.
DO $$
DECLARE
  t text;
BEGIN
  FOREACH t IN ARRAY ARRAY['g2p_register_clusters', 'g2p_register_history_clusters', 'g2p_intake_form_clusters'] LOOP
    IF to_regclass('public.' || t) IS NOT NULL THEN
      EXECUTE format('ALTER TABLE public.%I ADD COLUMN IF NOT EXISTS programme_cluster_code varchar', t);
      EXECUTE format('CREATE INDEX IF NOT EXISTS %I ON public.%I (programme_cluster_code)',
                     'ix_' || t || '_programme_cluster_code', t);
    END IF;
  END LOOP;
END $$;

-- 2. Typed cluster codes become the programme cluster code too. A generated ID
--    (CL- and digits only) or a pending one (TEMP-...) is not a programme code.
DO $$
BEGIN
  IF to_regclass('public.g2p_register_clusters') IS NOT NULL THEN
    UPDATE public.g2p_register_clusters
       SET programme_cluster_code = functional_record_id
     WHERE coalesce(programme_cluster_code, '') = ''
       AND functional_record_id LIKE 'CL-%'
       AND functional_record_id !~ '^CL-[0-9]+$';
  END IF;
END $$;

-- 3. The Cluster register generates its functional IDs.
UPDATE "public"."g2p_register_definitions"
   SET functional_id_generation_required = TRUE
 WHERE register_id = 'c5000000-0000-4000-8000-0000000c0001'
   AND functional_id_generation_required IS DISTINCT FROM TRUE;

-- 4. Search results and filters: Cluster ID, and Programme Cluster Code. Same JSON
--    as register-metadata/20_cluster_register.sql; only while the schema is still
--    the shipped one (a "Cluster Code" column).
UPDATE "public"."g2p_register_schemas"
   SET search_result_schema = '[{"field_name": "functional_record_id", "display_label": "Cluster ID", "order": 1}, {"field_name": "programme_cluster_code", "display_label": "Programme Cluster Code", "order": 2}, {"field_name": "cluster_name", "display_label": "Cluster Name", "order": 3}, {"field_name": "crop", "display_label": "Crop", "order": 4}, {"field_name": "geo_lowest_level_value_id", "display_label": "Woreda", "order": 5}, {"field_name": "number_of_smallholders", "display_label": "Smallholders", "order": 6}, {"field_name": "cluster_area_ha", "display_label": "Area (ha)", "order": 7}]',
       filter_schema = '[{"field_name": "cluster_name", "display_label": "Cluster Name", "filter_type": "text", "order": 1, "allowed_operators": ["eq", "contains"]}, {"field_name": "programme_cluster_code", "display_label": "Programme Cluster Code", "filter_type": "text", "order": 2, "allowed_operators": ["eq", "contains"]}, {"field_name": "crop", "display_label": "Crop", "filter_type": "text", "order": 3, "allowed_operators": ["eq", "contains"]}, {"field_name": "geo_lowest_level_value_id", "display_label": "Woreda", "filter_type": "text", "order": 4, "allowed_operators": ["eq", "contains"]}, {"field_name": "established_year", "display_label": "Established Year", "filter_type": "number", "order": 5, "allowed_operators": ["eq", "gt", "lt"]}, {"field_name": "record_status", "display_label": "Record Status", "filter_type": "dropdown", "order": 6, "allowed_operators": ["eq", "in"], "options_source": [{"value": "ACTIVE", "label": "ACTIVE"}, {"value": "INACTIVE", "label": "INACTIVE"}, {"value": "ARCHIVED", "label": "ARCHIVED"}]}]'
 WHERE register_id = 'c5000000-0000-4000-8000-0000000c0001'
   AND search_result_schema::text LIKE '%"display_label": "Cluster Code"%';

-- 5. The Cluster section's identity panel: Cluster ID read-only, the programme
--    code an optional input. Same JSON as 20_cluster_register.sql; only while the
--    panel is still the shipped one (an editable "Cluster code").
UPDATE "public"."g2p_register_sections"
   SET section_ui_schema = jsonb_set(
         section_ui_schema,
         '{panels,0,panels,0}',
         '{"widgets": [{"widget": "text", "widget-id": "functional_record_id", "widget-type": "input", "widget-label": "Cluster ID", "widget-readonly": true, "widget-required": false, "widget-data-path": "c5000000-0000-4000-8000-0000000c0001.functional_record_id"}, {"widget": "text", "widget-id": "programme_cluster_code", "widget-type": "input", "widget-label": "Programme Cluster Code", "widget-readonly": false, "widget-required": false, "widget-data-path": "c5000000-0000-4000-8000-0000000c0001.programme_cluster_code"}, {"widget": "text", "widget-id": "cluster_name", "widget-type": "input", "widget-label": "Cluster name", "widget-readonly": false, "widget-required": true, "widget-data-path": "c5000000-0000-4000-8000-0000000c0001.cluster_name"}], "panel-id": "panel_cluster_identity", "panel-orientation": "vertical"}'::jsonb),
       section_description = 'Cluster ID, programme cluster code, name, crop, establishment and coordinator'
 WHERE section_id = 'cluster_cluster_details_section_01'
   AND section_ui_schema #>> '{panels,0,panels,0,panel-id}' = 'panel_cluster_identity'
   AND section_ui_schema #>> '{panels,0,panels,0,widgets,0,widget-label}' = 'Cluster code';

UPDATE "public"."g2p_intake_form_definitions"
   SET form_description = 'Registers a new farmer cluster: programme cluster code, name, crop, coordinator, woreda and resources. The Cluster ID is generated on approval.'
 WHERE form_id = 'c5000000-0000-4000-8000-0000000c0011'
   AND form_description = 'Registers a new farmer cluster: code, name, crop, coordinator, woreda and resources.';
