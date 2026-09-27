INSERT INTO "public"."g2p_registry_documents" ("document_id","document_store_id","bucket","source_filename","created_by","created_at") VALUES
('c5000000-0000-4000-8000-0000000003a1','dci_commons_response.json.j2','templates','dci_commons_response.json.j2','seeder','2026-09-26 00:00:00'),
('c5000000-0000-4000-8000-0000000003a2','crop_sown_activity_to_dci.json.j2','templates','crop_sown_activity_to_dci.json.j2','seeder','2026-09-26 00:00:00')
ON CONFLICT DO NOTHING;
