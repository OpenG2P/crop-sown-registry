#!/usr/bin/env bash
# Write local/.env for the hybrid stack from cluster Secrets and the local dev DB
# password. Values are written to the file only, never printed.
#   ./make-env.sh <path-to-csr_dev-password-file>
set -euo pipefail
NS="${NS:-trial}"
cd "$(dirname "$0")"
secret() { kubectl -n "$NS" get secret "$1" -o jsonpath="{.data.$2}" | base64 -d; }
umask 077
{
  echo "CSR_DB_PASSWORD=$(cat "${1:?password file for csr_dev_user}")"
  echo "MASTER_DATA_DB_PASSWORD=$(secret master-data-db master-data-db-user)"
} > .env
echo "wrote local/.env"
