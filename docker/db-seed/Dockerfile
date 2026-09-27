# Crop Sown Registry — DB-seed image.
#
# The base image's entrypoint runs every *.sql under /seed/meta_data (sorted)
# and uploads /seed/templates to MinIO. The Crop Sown seed is:
#   register-metadata/   the CropSown ACTIVITY register definition
#   activity-metadata/   activity types (JSON Schemas, rules), indicators, ODK forms
#   templates/           DCI rendering of an activity
# No code lists: the registry reads them live from Master Data (ETH pack,
# agriculture domain, loaded by the master-data chart).
# There are no sample records: activities are created through the APIs.
#
# Build context = repo root.
ARG RP_VERSION=0.0.0-develop.439
FROM openg2p/openg2p-registry-db-seed:${RP_VERSION}

RUN rm -rf /seed/meta_data/* /seed/awe_meta_data/* /seed/templates/* /seed/seed-data/*

COPY crop-sown-extension/src/openg2p_registry_crop_sown_extension/meta_data/     /seed/meta_data/
COPY crop-sown-extension/src/openg2p_registry_crop_sown_extension/awe_meta_data/ /seed/awe_meta_data/
COPY crop-sown-extension/src/openg2p_registry_crop_sown_extension/templates/     /seed/templates/
