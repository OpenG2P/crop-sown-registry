# openg2p-registry-crop-sown-extension

The Crop Sown Registry's domain, installed into the OpenG2P registry-platform
images and selected with `REGISTRY_EXTENSION_MODULE=openg2p_registry_crop_sown_extension`.

It holds a single **activity register**, `CropSown`: append-only activities
(planned, land prepared, sown, cluster enrolled, growth observed, infestation,
damage, harvested) grouped by crop season — one crop on one plot in one season —
with a current-state projection per crop season.

| Path | What |
|---|---|
| `register_domain/models/crop_sown.py` | `G2PActivityCropSown` (activity table, promoted columns) and `G2PActivityProjectionCropSown` (crop season status) |
| `register_domain/services/crop_sown_domain_service.py` | Context key, derived yield, plausibility warnings, projection |
| `meta_data/` | Seed SQL. Activity types, indicators and ODK mapping are **generated** by `scripts/build_seed_sql.py` from `scripts/activity_definitions.py` |
| `templates/` | DCI rendering of an activity |
