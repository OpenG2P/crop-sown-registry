# Hybrid run

Run the Crop Sown Registry images on a laptop against a cluster's commons
services, with the same env var names the Helm chart uses.

| From the cluster (port-forward) | Local containers |
|---|---|
| Postgres: a dedicated `csr_dev` database, and `master_data` (read: code lists, geography) | staff-api, partner-api, celery worker and beat, db-seed |
| ODK Central (activity pull, optional) | Redis |
| | MinIO — so the shared templates bucket is not touched |

## Once per cluster

Create the database and user (as the cluster's Postgres admin), with `pg_trgm`:

```sql
CREATE ROLE csr_dev_user LOGIN PASSWORD '<password>';
CREATE DATABASE csr_dev OWNER csr_dev_user;
\c csr_dev
CREATE EXTENSION IF NOT EXISTS pg_trgm;
```

## Run

```bash
./local/port-forward.sh                                   # terminal 1 (NS=trial by default)
./local/make-env.sh <file holding the csr_dev password>   # writes local/.env (not committed)
docker-compose -f local/docker-compose.hybrid.yml --env-file local/.env -p csr-hybrid up -d
python3 scripts/e2e_smoke.py --partner-url http://localhost:18006 \
    --db-url "postgresql://csr_dev_user:<password>@localhost:15432/csr_dev"
```

Images default to `openg2p/openg2p-crop-sown-registry-*:local` (set `CSR_TAG`).
Build them from locally built registry-platform images:

```bash
# in registry-platform
for s in staff-api partner-api celery db-seed; do docker build -f docker/$s/Dockerfile -t openg2p/openg2p-registry-$s:<RP_VERSION> .; done
# here
for s in staff-api partner-api celery db-seed; do docker build -f docker/$s/Dockerfile -t openg2p/openg2p-crop-sown-registry-${s}:local .; done
```

The cluster's Master Data must hold the ETH pack's agriculture domain (the
master-data chart with `geoSeed.domains: [agriculture]`, from an openg2p-data that
has the crop-season lists). The registry reads every code list there; without
them each activity fails with "not a known code".

## What this does not cover

Staff API calls need a token from the cluster's Keycloak carrying Crop Sown
roles, and IAM to know the `activity:*` permissions; both exist only after the
Helm install (keycloak-init and iam-register jobs). Staff UI and staff API flows
are tested on the Helm install. Partner signature and consent enforcement are
off in the hybrid run and on in the chart.
