#!/usr/bin/env bash
# Dev-only stand-in for db-seed's LOAD_ATTRIBUTES when the Master Data API
# refuses anonymous reads: copy the agriculture code lists the Crop Sown
# Registry uses straight from the master_data DB (read-only) into csr_dev,
# with the same ids load_attributes_from_mds.py would write.
set -euo pipefail
cd "$(dirname "$0")"
set -a; . ./.env; set +a
PSQL=(docker run --rm -i --platform linux/arm64 postgres:16 psql -h host.docker.internal -p 15432 -v ON_ERROR_STOP=1)
LISTS="'CROP_COMMODITY','SOIL_FERTILITY','WATER_SOURCE'"
{
  docker run --rm --platform linux/arm64 -e PGPASSWORD="$MASTER_DATA_DB_PASSWORD" postgres:16 \
    psql -h host.docker.internal -p 15432 -U master_data_user -d master_data -At -c "
      select format('INSERT INTO g2p_attributes (attribute_id, attribute_code, attribute_display, is_hierarchical) VALUES (%L, %L, %L, false) ON CONFLICT (attribute_id) DO NOTHING;',
                    attribute_id, attribute_code, attribute_display)
      from g2p_attributes where attribute_code in ($LISTS);
      select format('INSERT INTO g2p_attribute_values (value_id, attribute_id, value_code, value_display, sort_order) VALUES (%L, %L, %L, %L, %s) ON CONFLICT (value_id) DO NOTHING;',
                    v.attribute_id || ':' || v.value_id, v.attribute_id, v.value_code, v.value_display, coalesce(v.sort_order, 0))
      from g2p_attribute_values v join g2p_attributes a on a.attribute_id = v.attribute_id where a.attribute_code in ($LISTS);"
} | docker run --rm -i --platform linux/arm64 -e PGPASSWORD="$CSR_DB_PASSWORD" postgres:16 \
      psql -h host.docker.internal -p 15432 -U csr_dev_user -d csr_dev -q -v ON_ERROR_STOP=1
echo "copied agriculture code lists into csr_dev"
