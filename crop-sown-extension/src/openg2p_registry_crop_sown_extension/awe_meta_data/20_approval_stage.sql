INSERT INTO "public"."approval_stage" (
    "id",
    "policy_id",
    "stage_order",
    "name",
    "mode",
    "mode_value",
    "sla_hours",
    "parallel_group",
    "skip_if",
    "on_empty",
    "on_breach",
    "escalation_rules_json",
    "created_at",
    "updated_at"
)
SELECT v."id", v."policy_id", v."stage_order"::int, v."name", v."mode",
       v."mode_value"::int, v."sla_hours"::int, v."parallel_group"::int,
       v."skip_if"::json, v."on_empty", v."on_breach",
       v."escalation_rules_json"::json, v."created_at"::timestamptz, v."updated_at"::timestamptz
FROM (VALUES
    ('c5000000-0000-4000-8000-0000000c0051', 'c5000000-0000-4000-8000-0000000c0041', 1, 'Stage 1 Officers', 'all', NULL, NULL, NULL, 'null', 'block', NULL, 'null', NOW(), NOW()),
    ('c5000000-0000-4000-8000-0000000c0052', 'c5000000-0000-4000-8000-0000000c0041', 2, 'Stage 2 Officers', 'all', NULL, NULL, NULL, 'null', 'block', NULL, 'null', NOW(), NOW()),
    ('c5000000-0000-4000-8000-0000000c0053', 'c5000000-0000-4000-8000-0000000c0042', 1, 'Stage 1 Officers', 'all', NULL, NULL, NULL, 'null', 'block', NULL, 'null', NOW(), NOW()),
    ('c5000000-0000-4000-8000-0000000c0054', 'c5000000-0000-4000-8000-0000000c0042', 2, 'Stage 2 Officers', 'all', NULL, NULL, NULL, 'null', 'block', NULL, 'null', NOW(), NOW())
) AS v("id","policy_id","stage_order","name","mode","mode_value","sla_hours",
        "parallel_group","skip_if","on_empty","on_breach","escalation_rules_json",
        "created_at","updated_at")
-- Skip stages whose policy is absent (skipped above on a shared-DB conflict), so
-- one orphan's FK violation does not abort the whole statement.
WHERE EXISTS (SELECT 1 FROM "public"."approval_policy" p WHERE p.id = v."policy_id")
ON CONFLICT DO NOTHING;
