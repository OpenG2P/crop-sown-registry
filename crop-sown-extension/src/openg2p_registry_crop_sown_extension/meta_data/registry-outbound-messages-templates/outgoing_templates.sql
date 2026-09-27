-- DCI search on the CropSown activity register renders each activity with crop_sown_activity_to_dci.json.j2
INSERT INTO "public"."outgoing_templates" ("template_id","data_model_id","register_id","template_document_id","created_at","updated_at") VALUES
('c5000000-0000-4000-8000-0000000003e1','c5000000-0000-4000-8000-0000000003d1','c5000000-0000-4000-8000-000000000001','c5000000-0000-4000-8000-0000000003a2','2026-09-26 00:00:00',NULL)
ON CONFLICT DO NOTHING;
