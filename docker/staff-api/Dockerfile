# Crop Sown Registry — staff-api image.
#
# Thin layer over the registry-platform base image: installs the crop-sown
# extension and selects it with REGISTRY_EXTENSION_MODULE. ENV defaults and the
# migrate + gunicorn CMD come from the base image. The platform migration creates
# the activity tables (partitioned, append-only) this extension declares.
#
# RP_VERSION must be a registry-platform build that includes activity registers
# (feature/activity-register). Keep it in lockstep with the openg2p-registry
# dependency in helm/openg2p-crop-sown-registry/Chart.yaml (scripts/bump-rp-version.sh).
#
# Build context = repo root.
ARG RP_VERSION=0.0.0-develop.608
FROM openg2p/openg2p-registry-staff-api:${RP_VERSION}

ENV REGISTRY_EXTENSION_MODULE=openg2p_registry_crop_sown_extension

COPY crop-sown-extension/ /app/crop-sown-extension/
RUN pip install --no-cache-dir /app/crop-sown-extension
