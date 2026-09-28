# Crop Sown Registry

An OpenG2P registry of **crop seasons**: what each farmer plans, prepares, sows,
observes and harvests on each plot, season by season. It holds a single
**activity register** — append-only activities grouped by crop season (one crop
on one plot in one season), a current-state view per crop season, work lists
and indicators — built on the OpenG2P registry platform.

Design: [Agri Stack docs — Crop Sown Registry](https://github.com/OpenG2P/agri-stack/blob/develop/docs/crop-sown-registry.md)
and [Activity register](https://github.com/OpenG2P/agri-stack/blob/develop/docs/activity-register.md).

## What this repo owns

| Path | What |
|---|---|
| `crop-sown-extension/` | The domain: activity and projection models, domain service (context key, derived yield, plausibility warnings, projection), seed SQL, DCI template |
| `scripts/activity_definitions.py` | Activity types (JSON Schemas, rules naming Master Data code lists), indicators, ODK mapping — the one place to edit |
| `scripts/build_seed_sql.py` | Generates the seed SQL from the definitions (`--check` in CI) |
| `docker/` | Thin images `FROM` the registry-platform images: staff-api, partner-api, celery, db-seed |
| `helm/openg2p-crop-sown-registry/` | Values overlay over the `openg2p-registry` chart |
| `test/integration/` | The extension through the platform's activity services on a real PostgreSQL |
| `scripts/e2e_smoke.py` | A crop season end to end through a running partner API (+ DB checks) |
| `local/` | Hybrid run: these containers on a laptop against a cluster's commons |

The registry-platform version is pinned in `docker/*/Dockerfile` (`RP_VERSION`)
and `helm/.../Chart.yaml`, kept in lockstep by `scripts/bump-rp-version.sh` (runs from any directory).
Activity registers need `0.0.0-develop.438` or later; reading code lists from
Master Data needs `0.0.0-develop.439` or later. The season summary needs the
registry-platform release after `0.0.0-develop.439` that adds activity aggregates.

## Season summary

The domain service's `aggregate` hook keeps `FARMER_SEASON_SUMMARY` per farmer,
crop year and season, recomputed from the crop-season projections by the outbox
worker, with history (`/activity/search_aggregates`, `/activity/get_aggregate_history`).

## Code lists come from Master Data

This registry keeps no code lists. Every coded field — crop, season, seed type,
fertiliser, pest, severity, ... — names a Master Data list, and the platform
checks codes against Master Data live, as the Farmer Registry does. The lists
are the ETH country pack's agriculture domain in
[openg2p-data](https://github.com/OpenG2P/openg2p-data/tree/develop/packs/ETH/domains/agriculture)
(`CROP_COMMODITY`, `CROP_SEASON`, `SEED_TYPE`, `INFESTATION_SEVERITY`, ...), with
list-prefixed codes such as `CROP_TEFF`, `SEASON_MEHER`, `SEV_HIGH`.

Install Master Data with that domain before this registry:

```yaml
# openg2p-master-data values
geoSeed:
  countryPack: ETH
  domains: [agriculture]
```

To add or change a code, change the pack, not this repo.

## Tests

```bash
# Integration tests (needs registry-platform core, openg2p-data beside this repo or $OPENG2P_DATA_DIR,
# and a disposable Postgres)
docker run -d --name csr-pg -e POSTGRES_PASSWORD=postgres -p 55432:5432 postgres:16
docker exec csr-pg psql -U postgres -c "create database csr_test"
pip install -e <registry-platform>/core/openg2p-registry-core -e crop-sown-extension pytest pytest-asyncio
pytest test/integration

# Generated seed SQL is current; every code list and code used is in the ETH pack
python3 scripts/build_seed_sql.py --check
pytest test/test_code_lists_in_pack.py
```

## Hybrid run against a cluster

See [local/README.md](local/README.md).
