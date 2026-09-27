#!/usr/bin/env bash
# Forward the trial commons services the hybrid stack uses to localhost.
#   15432 -> commons-postgresql (csr_dev registry DB + master_data, whose code lists the APIs read)
#   18383 -> ODK Central backend (activity ODK pull)
# Ctrl-C stops all forwards.
set -euo pipefail
NS="${NS:-trial}"
trap 'kill 0' EXIT
kubectl -n "$NS" port-forward svc/commons-postgresql 15432:5432 &
kubectl -n "$NS" port-forward svc/commons-services-odk-central-backend 18383:80 &
wait
