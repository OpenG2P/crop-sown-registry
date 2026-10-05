# Crop Sown Registry — DB-seed image.
#
# The base image's entrypoint runs every *.sql under /seed/meta_data (sorted)
# and uploads /seed/templates to MinIO. The Crop Sown seed is:
#   register-metadata/   the CropSown ACTIVITY register definition, and the
#                        Cluster entity register (sections, tabs, intake form)
#   awe-integration/     Cluster change requests / intake forms -> AWE policy keys
#   activity-metadata/   activity types (JSON Schemas, rules), indicators, ODK forms
#   zz-upgrades/         brings an existing install's Cluster register to the
#                        current metadata (runs last; idempotent)
#   templates/           DCI rendering of an activity
#   awe_meta_data/       Cluster approval policies + this release's callback secret
#                        (run against the shared AWE database)
# No code lists: the registry reads them live from Master Data (ETH pack,
# agriculture domain, loaded by the master-data chart).
# Sample data (LOAD_SAMPLE_DATA=true) is two approved clusters, inserted by
# load_sample_data.py; crop-season activities are created through the APIs.
#
# Build context = repo root.
ARG RP_VERSION=0.0.0-develop.604
FROM openg2p/openg2p-registry-db-seed:${RP_VERSION}

RUN rm -rf /seed/meta_data/* /seed/awe_meta_data/* /seed/templates/* /seed/seed-data/*

COPY crop-sown-extension/src/openg2p_registry_crop_sown_extension/meta_data/     /seed/meta_data/
COPY crop-sown-extension/src/openg2p_registry_crop_sown_extension/awe_meta_data/ /seed/awe_meta_data/
COPY crop-sown-extension/src/openg2p_registry_crop_sown_extension/templates/     /seed/templates/

# The registry's own sample loader: the entrypoint keeps the hook, the variant
# supplies the loader (as the Farmer Registry does).
COPY docker/db-seed/load_sample_data.py /seed/load_sample_data.py
RUN chmod +x /seed/load_sample_data.py
