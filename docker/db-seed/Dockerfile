# Crop Sown Registry — DB-seed image.
#
# The base image's entrypoint runs every *.sql under /seed/meta_data (sorted),
# uploads /seed/templates to MinIO and, with LOAD_ATTRIBUTES, copies the
# country's code lists (CROP_COMMODITY, SOIL_FERTILITY, WATER_SOURCE from the
# agriculture domain) from Master Data. The Crop Sown seed is:
#   register-metadata/   the CropSown ACTIVITY register definition
#   activity-metadata/   activity types (JSON Schemas, rules), indicators, ODK forms
#   lookup-data/         Ethiopia-defined CS_* code lists
#   templates/           DCI rendering of an activity
# There are no sample records: activities are created through the APIs.
#
# Build context = repo root.
ARG RP_VERSION=0.0.0-develop.438
FROM openg2p/openg2p-registry-db-seed:${RP_VERSION}

RUN rm -rf /seed/meta_data/* /seed/awe_meta_data/* /seed/templates/* /seed/seed-data/*

COPY crop-sown-extension/src/openg2p_registry_crop_sown_extension/meta_data/     /seed/meta_data/
COPY crop-sown-extension/src/openg2p_registry_crop_sown_extension/awe_meta_data/ /seed/awe_meta_data/
COPY crop-sown-extension/src/openg2p_registry_crop_sown_extension/templates/     /seed/templates/
