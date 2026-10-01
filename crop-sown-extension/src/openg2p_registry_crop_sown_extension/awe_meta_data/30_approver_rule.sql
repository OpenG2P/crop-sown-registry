-- Approvers are the platform chart's demo staff users (keycloak-init creates
-- alex.carter and nina.patel for every registry release).
INSERT INTO "public"."approver_rule" (
    "id",
    "stage_id",
    "rule_type",
    "rule_value",
    "kind",
    "required",
    "created_at",
    "updated_at"
)
SELECT v."id", v."stage_id", v."rule_type", v."rule_value"::json, v."kind",
       v."required"::boolean, v."created_at"::timestamptz, v."updated_at"::timestamptz
FROM (VALUES
    ('c5000000-0000-4000-8000-0000000c0061', 'c5000000-0000-4000-8000-0000000c0051', 'user', '{"user_id": "alex.carter"}', 'approver', 'FALSE', NOW(), NOW()),
    ('c5000000-0000-4000-8000-0000000c0062', 'c5000000-0000-4000-8000-0000000c0052', 'user', '{"user_id": "nina.patel"}', 'approver', 'FALSE', NOW(), NOW()),
    ('c5000000-0000-4000-8000-0000000c0063', 'c5000000-0000-4000-8000-0000000c0053', 'user', '{"user_id": "alex.carter"}', 'approver', 'FALSE', NOW(), NOW()),
    ('c5000000-0000-4000-8000-0000000c0064', 'c5000000-0000-4000-8000-0000000c0054', 'user', '{"user_id": "nina.patel"}', 'approver', 'FALSE', NOW(), NOW())
) AS v("id","stage_id","rule_type","rule_value","kind","required","created_at","updated_at")
WHERE EXISTS (SELECT 1 FROM "public"."approval_stage" s WHERE s.id = v."stage_id")
ON CONFLICT DO NOTHING;
