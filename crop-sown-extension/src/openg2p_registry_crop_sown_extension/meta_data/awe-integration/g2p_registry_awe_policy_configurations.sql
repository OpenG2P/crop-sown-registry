-- Cluster change requests and cluster intake forms are approved in AWE under these
-- policy keys (seeded into the shared AWE database by awe_meta_data/). The CropSown
-- activity register has no change requests, so no binding.
INSERT INTO "public"."g2p_registry_awe_policy_configurations" (
    "awe_policy_config_id",
    "policy_scope",
    "register_id",
    "intake_form_id",
    "section_id",
    "policy_type",
    "policy_key",
    "context_field_names"
) VALUES
    ('c5000000-0000-4000-8000-0000000c0031', 'REGISTER', 'c5000000-0000-4000-8000-0000000c0001', '', '', 'registry.change_request', 'registry.change_request.cluster', 'null'),
    ('c5000000-0000-4000-8000-0000000c0032', 'INTAKE_FORM', 'c5000000-0000-4000-8000-0000000c0001', 'c5000000-0000-4000-8000-0000000c0011', '', 'registry.intake_form', 'registry.intake_form.cluster', 'null')
ON CONFLICT ("awe_policy_config_id") DO NOTHING;
