# Crop Sown Registry — Celery image (worker and beat, chosen by CELERY_APP).
#
# The worker runs the activity outbox, projection reconciliation, partition
# maintenance and the ODK Central pull; beat schedules them.
#
# Build context = repo root.
ARG RP_VERSION=0.0.0-develop.611
FROM openg2p/openg2p-registry-celery:${RP_VERSION}

ENV REGISTRY_EXTENSION_MODULE=openg2p_registry_crop_sown_extension

COPY crop-sown-extension/ /app/crop-sown-extension/
RUN pip install --no-cache-dir /app/crop-sown-extension
