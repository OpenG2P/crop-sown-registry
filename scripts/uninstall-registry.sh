#!/usr/bin/env bash
#
# uninstall-registry.sh
# ---------------------
# Cleanly uninstall the Crop Sown Registry Helm release and every resource it
# touched, including the PostgreSQL database and role that live inside the
# commons-postgresql instance (which are NOT owned by the registry Helm release
# and therefore survive `helm uninstall`). Adapted from the Farmer Registry's
# script; the Crop Sown Registry ships no Superset dashboards, so there is no
# dashboard step.
#
# What it does, in order:
#   1. helm uninstall <release>            (registry workloads, services,
#                                           helm-owned secrets & configmaps)
#   2. Delete leftover Jobs + their Pods   (helm hook jobs like db-seed,
#                                           keycloak-init, postgres-init,
#                                           iam-register and sanity keep
#                                           themselves around via
#                                           hook-delete-policy: before-hook-creation)
#   3. Sweep leftover Secrets/ConfigMaps   (label: app.kubernetes.io/instance)
#   4. Drop Postgres databases + roles     (via `kubectl exec` into
#                                           commons-postgresql-0). The registry DB
#                                           always; the ID-generator and AWE DBs
#                                           only if an install enabled them.
#   5. Delete this registry's IAM rows     (staff_portal_applications +
#                                           staff_roles / permissions / mappings
#                                           for mnemonic <release>-staff-portal,
#                                           in the IAM DB inside the same
#                                           commons-postgresql instance)
#   6. Delete PVCs by label                (app.kubernetes.io/instance)
#   7. Delete the PVs those PVCs claimed    (typically `Released` PVs created with
#                                           reclaimPolicy=Retain), and PVs labelled
#                                           with the release — never other releases'
#                                           PVs in a shared namespace
#
# NOT removed (by design), because they live in shared services rather than in
# this release or its DB:
#   * the Keycloak client <release>-staff-portal and its roles (keycloak-init);
#   * the DCI templates db-seed uploaded to the shared MinIO `templates` bucket
#     (crop_sown_activity_to_dci.json.j2; dci_commons_response.json.j2 is shared
#     with other registries);
#   * code lists and geography in Master Data, which other registries use;
#   * ODK Central projects/forms and the ODK credentials Secret, if created by hand.
#
# Requires: kubectl (cluster admin), helm, bash 4+.
#
# USAGE:
#   ./uninstall-registry.sh \
#       --namespace <ns> \
#       [--release <name>]            (default: csr)
#       [--postgres-release <name>]   (default: commons-postgresql)
#       [--postgres-namespace <ns>]   (default: same as --namespace)
#       [--iam-db <name>]             (default: iam; IAM staff-portal DB to clean)
#       [--keep-iam]                  (do NOT delete this registry's IAM rows)
#       [--keep-pvs]                  (delete PVCs but not PVs)
#       [--dry-run]                   (print actions, change nothing)
#       [--yes]                       (skip interactive confirmation)
#
# EXAMPLES:
#   # Dry run first — no changes made:
#   ./uninstall-registry.sh --namespace trial --dry-run
#
#   # For real, with confirmation prompt:
#   ./uninstall-registry.sh --namespace trial
#
#   # Non-interactive (CI / scripted):
#   ./uninstall-registry.sh --namespace trial --yes

set -euo pipefail

# ---------- defaults ----------
RELEASE="csr"
NAMESPACE=""
POSTGRES_RELEASE="commons-postgresql"
POSTGRES_NAMESPACE=""
IAM_DB="iam"
KEEP_IAM=false
KEEP_PVS=false
DRY_RUN=false
ASSUME_YES=false

# ---------- cli ----------
usage() { sed -n '2,/^set -euo/p' "$0" | sed '$d'; exit 1; }

while [[ $# -gt 0 ]]; do
  case "$1" in
    --release)           RELEASE="$2";           shift 2 ;;
    --namespace|-n)      NAMESPACE="$2";         shift 2 ;;
    --postgres-release)  POSTGRES_RELEASE="$2";  shift 2 ;;
    --postgres-namespace) POSTGRES_NAMESPACE="$2"; shift 2 ;;
    --iam-db)            IAM_DB="$2";            shift 2 ;;
    --keep-iam)          KEEP_IAM=true;          shift ;;
    --keep-pvs)          KEEP_PVS=true;          shift ;;
    --dry-run)           DRY_RUN=true;           shift ;;
    --yes|-y)            ASSUME_YES=true;        shift ;;
    -h|--help)           usage ;;
    *) echo "Unknown argument: $1"; usage ;;
  esac
done

[[ -z "$NAMESPACE" ]] && { echo "ERROR: --namespace is required"; exit 1; }
[[ -z "$POSTGRES_NAMESPACE" ]] && POSTGRES_NAMESPACE="$NAMESPACE"

# ---------- derived: DB / user names (templated exactly like values.yaml) ----------
# values.yaml:
#   registryDB:        '{{ .Release.Name | replace "-" "_" }}'
#   registryDBUser:    '{{ printf "%s_user" .Release.Name | replace "-" "_" }}'
#   idGeneratorDB:     '{{ printf "%s_idgenerator" .Release.Name | replace "-" "_" }}'
#   idGeneratorDBUser: '{{ printf "%s_idgenerator_user" .Release.Name | replace "-" "_" }}'
RELEASE_UNDERSCORED="${RELEASE//-/_}"
REGISTRY_DB="${RELEASE_UNDERSCORED}"
REGISTRY_USER="${RELEASE_UNDERSCORED}_user"
IDGEN_DB="${RELEASE_UNDERSCORED}_idgenerator"
IDGEN_USER="${RELEASE_UNDERSCORED}_idgenerator_user"
# The ID generator (Cluster IDs) and AWE (Cluster approvals) each have their own
# DB and role; they are dropped only if the install has them (DROP ... IF
# EXISTS). The AWE role must go, else a reinstall regenerates the
# `<release>-awe` secret while the role keeps its old password.
#   values.yaml: aweDB '{{ .Release.Name }}_awe', aweDBUser '{{ .Release.Name }}_awe_user'
AWE_DB="${RELEASE_UNDERSCORED}_awe"
AWE_USER="${RELEASE_UNDERSCORED}_awe_user"

# IAM staff-portal application mnemonic == the per-release Keycloak client_id,
# templated in values.yaml as `{{ .Release.Name }}-staff-portal` (hyphenated,
# NOT underscored like the DB names above).
IAM_APP_MNEMONIC="${RELEASE}-staff-portal"

# ---------- helpers ----------
_red()   { printf "\033[31m%s\033[0m\n" "$*"; }
_green() { printf "\033[32m%s\033[0m\n" "$*"; }
_yellow(){ printf "\033[33m%s\033[0m\n" "$*"; }
_blue()  { printf "\033[34m%s\033[0m\n" "$*"; }

run() {
  # Print + execute, or just print if --dry-run.
  # Never aborts the script on non-zero exit — cleanup commands must be
  # idempotent. Already-deleted resources produce a notice and we move on.
  echo "  \$ $*"
  if [[ "$DRY_RUN" == false ]]; then
    eval "$@" || _yellow "  (command returned non-zero — continuing)"
  fi
}

# Run a shell snippet, honouring DRY_RUN. Use when `run` can't quote safely.
run_block() {
  local label="$1"; shift
  echo "  [${label}]"
  if [[ "$DRY_RUN" == false ]]; then
    "$@" || _yellow "  (block returned non-zero — continuing)"
  fi
}

kexec_psql() {
  # Run SQL as postgres superuser inside the commons-postgresql pod.
  # Uses PGPASSWORD from the pod's env so no secret reads are needed on
  # the admin's machine. Tolerant of failure — script continues.
  local sql="$1"
  local cmd=(kubectl exec -n "$POSTGRES_NAMESPACE" "$PG_POD" -c postgresql -- \
             bash -c "PGPASSWORD=\"\$POSTGRES_PASSWORD\" psql -U postgres -v ON_ERROR_STOP=0 -c \"$sql\"")
  echo "  \$ psql -U postgres -c \"$sql\""
  if [[ "$DRY_RUN" == false ]]; then
    "${cmd[@]}" || _yellow "  (psql returned non-zero — continuing)"
  fi
}

kexec_psql_db() {
  # Like kexec_psql, but connects to a specific database (-d). Used to clean
  # this registry's rows out of the IAM staff-portal database, which lives in
  # the same commons-postgresql instance. Tolerant of failure — continues.
  local db="$1"
  local sql="$2"
  local cmd=(kubectl exec -n "$POSTGRES_NAMESPACE" "$PG_POD" -c postgresql -- \
             bash -c "PGPASSWORD=\"\$POSTGRES_PASSWORD\" psql -U postgres -d \"$db\" -v ON_ERROR_STOP=0 -c \"$sql\"")
  echo "  \$ psql -U postgres -d $db -c \"$sql\""
  if [[ "$DRY_RUN" == false ]]; then
    "${cmd[@]}" || _yellow "  (psql returned non-zero — continuing)"
  fi
}

kexec_psql_capture() {
  # Run a read-only query and echo the trimmed result to stdout. Quiet (no
  # command echo, errors suppressed) — used for existence checks so we can skip
  # gracefully when the IAM DB / tables are absent. Returns empty on any error.
  local db="$1"
  local sql="$2"
  kubectl exec -n "$POSTGRES_NAMESPACE" "$PG_POD" -c postgresql -- \
    bash -c "PGPASSWORD=\"\$POSTGRES_PASSWORD\" psql -U postgres -d \"$db\" -tAc \"$sql\"" 2>/dev/null \
    | tr -d '[:space:]' || true
}

# ---------- pre-flight ----------
_blue "==> Pre-flight checks"

command -v kubectl >/dev/null || { _red "kubectl not found"; exit 1; }
command -v helm    >/dev/null || { _red "helm not found";    exit 1; }

if kubectl get ns "$NAMESPACE" >/dev/null 2>&1; then
  NAMESPACE_EXISTS=true
  _green "  Namespace '$NAMESPACE' exists"
else
  NAMESPACE_EXISTS=false
  _yellow "  Namespace '$NAMESPACE' does not exist — namespace-scoped cleanup will be skipped"
fi

# Locate commons-postgresql pod. Bitnami's chart gives it these labels.
PG_POD=""
if kubectl get ns "$POSTGRES_NAMESPACE" >/dev/null 2>&1; then
  PG_POD=$(kubectl get pod -n "$POSTGRES_NAMESPACE" \
    -l "app.kubernetes.io/instance=$POSTGRES_RELEASE,app.kubernetes.io/name=postgresql" \
    -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || true)

  # Fallback: by name.
  if [[ -z "$PG_POD" ]]; then
    if kubectl get pod -n "$POSTGRES_NAMESPACE" "${POSTGRES_RELEASE}-0" >/dev/null 2>&1; then
      PG_POD="${POSTGRES_RELEASE}-0"
    fi
  fi
fi

if [[ -z "$PG_POD" ]]; then
  PG_POD_FOUND=false
  _yellow "  commons-postgresql pod not found — DB / role drop step will be skipped"
  _yellow "  (tried label app.kubernetes.io/instance=$POSTGRES_RELEASE and pod name ${POSTGRES_RELEASE}-0 in namespace '$POSTGRES_NAMESPACE')"
else
  PG_POD_FOUND=true
  _green "  Found Postgres pod: $PG_POD (namespace: $POSTGRES_NAMESPACE)"
fi

# Helm release presence is not strictly required (user may have already uninstalled
# and is now running the cleanup half). Note it but don't abort.
if helm -n "$NAMESPACE" status "$RELEASE" >/dev/null 2>&1; then
  _green "  Helm release '$RELEASE' found in namespace '$NAMESPACE'"
  HELM_RELEASE_EXISTS=true
else
  _yellow "  Helm release '$RELEASE' not found — will skip helm uninstall step"
  HELM_RELEASE_EXISTS=false
fi

# ---------- show the blast radius ----------
_blue "==> Resources to be deleted"

echo
echo "Helm release:       $RELEASE (namespace: $NAMESPACE)"
echo "Postgres databases: $REGISTRY_DB (and, if present, $IDGEN_DB , $AWE_DB)"
echo "Postgres roles:     $REGISTRY_USER (and, if present, $IDGEN_USER , $AWE_USER)"
echo "Postgres pod:       ${PG_POD:-<not found — will skip DB drop>} ($POSTGRES_NAMESPACE)"
if [[ "$KEEP_IAM" == true ]]; then
  echo "IAM rows:           (skipped — --keep-iam)"
else
  echo "IAM rows:           mnemonic '$IAM_APP_MNEMONIC' in DB '$IAM_DB' (staff_portal_applications + roles/permissions/mappings)"
fi
echo

if [[ "$NAMESPACE_EXISTS" == true ]]; then
  echo "Jobs (label app.kubernetes.io/instance=$RELEASE):"
  kubectl -n "$NAMESPACE" get job -l "app.kubernetes.io/instance=$RELEASE" \
    --no-headers 2>/dev/null | awk '{print "  - " $1}' || echo "  (none)"

  echo "Secrets (label app.kubernetes.io/instance=$RELEASE):"
  kubectl -n "$NAMESPACE" get secret -l "app.kubernetes.io/instance=$RELEASE" \
    --no-headers 2>/dev/null | awk '{print "  - " $1}' || echo "  (none)"

  echo "ConfigMaps (label app.kubernetes.io/instance=$RELEASE):"
  kubectl -n "$NAMESPACE" get configmap -l "app.kubernetes.io/instance=$RELEASE" \
    --no-headers 2>/dev/null | awk '{print "  - " $1}' || echo "  (none)"

  echo "PVCs (label app.kubernetes.io/instance=$RELEASE):"
  kubectl -n "$NAMESPACE" get pvc -l "app.kubernetes.io/instance=$RELEASE" \
    --no-headers 2>/dev/null | awk '{print "  - " $1}' || echo "  (none)"
else
  echo "(namespace '$NAMESPACE' does not exist — no namespace-scoped resources to preview)"
fi

# PVs to delete: only those claimed by THIS release's PVCs, or labelled with the
# release. Never "every Released PV in the namespace" — in a shared namespace
# (commons, other registries) those belong to other releases. PVC names are
# captured now, because step 6 deletes the PVCs and their names with them.
OUR_PVCS=""
if [[ "$NAMESPACE_EXISTS" == true ]]; then
  OUR_PVCS=$(kubectl -n "$NAMESPACE" get pvc -l "app.kubernetes.io/instance=$RELEASE" \
               -o jsonpath='{.items[*].metadata.name}' 2>/dev/null || true)
fi
OUR_PVS=$( (kubectl get pv -o json 2>/dev/null || echo '{"items":[]}') | \
  jq -r --arg ns "$NAMESPACE" --arg rel "$RELEASE" --arg pvcs " $OUR_PVCS " '
    .items[]
    | select(
        (.spec.claimRef.namespace == $ns and ($pvcs | contains(" " + .spec.claimRef.name + " ")))
        or (.metadata.labels["app.kubernetes.io/instance"] == $rel))
    | .metadata.name' 2>/dev/null | sort -u | tr '\n' ' ' | sed 's/ *$//' || true)

if [[ "$KEEP_PVS" == false ]]; then
  echo "PVs (claimed by the PVCs above, or labelled with the release):"
  if [[ -n "$OUR_PVS" ]]; then
    for pv in $OUR_PVS; do echo "  - $pv"; done
  else
    echo "  (none)"
  fi
fi
echo

# ---------- confirmation ----------
if [[ "$DRY_RUN" == true ]]; then
  _yellow "DRY-RUN: no changes will be made."
fi

if [[ "$ASSUME_YES" == false && "$DRY_RUN" == false ]]; then
  _red "This is destructive. Type the release name ('$RELEASE') to confirm:"
  read -r CONFIRM
  if [[ "$CONFIRM" != "$RELEASE" ]]; then
    _red "Confirmation did not match. Aborting."
    exit 1
  fi
fi

# ========== STEP 1: helm uninstall ==========
_blue "==> [1/7] Helm uninstall"
if [[ "$HELM_RELEASE_EXISTS" == true ]]; then
  run "helm uninstall '$RELEASE' -n '$NAMESPACE' --wait --timeout 5m || true"
else
  echo "  (skipped — release not present)"
fi

# ========== STEP 2: delete leftover Jobs (and their Pods) ==========
# Helm hook Jobs (db-seed post-install, keycloak-init, postgres-init, iam-register,
# sanity) are created
# with `helm.sh/hook-delete-policy: before-hook-creation`, which means they are
# NOT cleaned up by `helm uninstall`. We delete them explicitly here — BEFORE
# dropping the DBs, so their Pods close their Postgres connections cleanly.
_blue "==> [2/7] Delete leftover Jobs and their Pods"
if [[ "$NAMESPACE_EXISTS" == true ]]; then
  run "kubectl -n '$NAMESPACE' delete job -l 'app.kubernetes.io/instance=$RELEASE' --ignore-not-found --wait=true --timeout=2m"
  # Orphan pods (completed/failed) that a Job left behind after TTL etc.
  run "kubectl -n '$NAMESPACE' delete pod -l 'app.kubernetes.io/instance=$RELEASE' --ignore-not-found --field-selector=status.phase!=Running"
else
  echo "  (skipped — namespace '$NAMESPACE' not present)"
fi

# ========== STEP 3: sweep leftover Secrets & ConfigMaps ==========
_blue "==> [3/7] Sweep leftover Secrets / ConfigMaps"
if [[ "$NAMESPACE_EXISTS" == true ]]; then
  run "kubectl -n '$NAMESPACE' delete secret    -l 'app.kubernetes.io/instance=$RELEASE' --ignore-not-found"
  run "kubectl -n '$NAMESPACE' delete configmap -l 'app.kubernetes.io/instance=$RELEASE' --ignore-not-found"
else
  echo "  (skipped — namespace '$NAMESPACE' not present)"
fi

# ========== STEP 4: drop Postgres DBs & roles ==========
_blue "==> [4/7] Drop Postgres databases and roles"
if [[ "$PG_POD_FOUND" == true ]]; then
  for db in "$REGISTRY_DB" "$IDGEN_DB" "$AWE_DB"; do
    echo "  - Database: $db"
    kexec_psql "REVOKE CONNECT ON DATABASE \\\"$db\\\" FROM PUBLIC;"
    kexec_psql "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '$db' AND pid <> pg_backend_pid();"
    kexec_psql "DROP DATABASE IF EXISTS \\\"$db\\\";"
  done

  for role in "$REGISTRY_USER" "$IDGEN_USER" "$AWE_USER"; do
    echo "  - Role: $role"
    # Reassign/drop stray ownership outside the dropped DBs (roles can own cluster-wide objects).
    kexec_psql "REASSIGN OWNED BY \\\"$role\\\" TO postgres;"
    kexec_psql "DROP OWNED BY \\\"$role\\\";"
    kexec_psql "DROP ROLE IF EXISTS \\\"$role\\\";"
  done
else
  echo "  (skipped — commons-postgresql pod not reachable; if Postgres is already gone, DBs are gone too)"
fi

# ========== STEP 5: clean this registry's IAM rows ==========
# IAM no longer seeds registry data — each registry self-registers its tile +
# roles/permissions into IAM at install time (keyed by application_mnemonic =
# <release>-staff-portal). `helm uninstall` does not touch IAM, so remove those
# rows here (child rows first). Targeted strictly by this release's mnemonic, so
# it never affects other registries or the keycloak/minio/superset singletons.
_blue "==> [5/7] Clean IAM staff-portal rows"
if [[ "$KEEP_IAM" == true ]]; then
  _yellow "  (skipped — --keep-iam)"
elif [[ "$PG_POD_FOUND" != true ]]; then
  echo "  (skipped — commons-postgresql pod not reachable; cannot reach IAM DB)"
elif [[ "$DRY_RUN" == true ]]; then
  echo "  Would delete IAM rows for mnemonic '$IAM_APP_MNEMONIC' from DB '$IAM_DB' (if the DB/tables exist)"
else
  # Tolerate an absent IAM install: if the IAM DB or its tables don't exist,
  # there is nothing to clean — report and move on without noisy psql errors.
  IAM_DB_EXISTS=$(kexec_psql_capture "postgres" "SELECT 1 FROM pg_database WHERE datname = '$IAM_DB'")
  if [[ "$IAM_DB_EXISTS" != "1" ]]; then
    _yellow "  (skipped — IAM database '$IAM_DB' not found)"
  else
    IAM_TABLE_EXISTS=$(kexec_psql_capture "$IAM_DB" "SELECT to_regclass('public.staff_portal_applications') IS NOT NULL")
    if [[ "$IAM_TABLE_EXISTS" != "t" ]]; then
      _yellow "  (skipped — table staff_portal_applications not found in IAM DB '$IAM_DB')"
    else
      echo "  - Application mnemonic: $IAM_APP_MNEMONIC (DB: $IAM_DB)"
      kexec_psql_db "$IAM_DB" "DELETE FROM staff_role_permissions WHERE role_id IN (SELECT id FROM staff_roles WHERE application_id IN (SELECT id FROM staff_portal_applications WHERE application_mnemonic = '$IAM_APP_MNEMONIC'));"
      kexec_psql_db "$IAM_DB" "DELETE FROM staff_roles WHERE application_id IN (SELECT id FROM staff_portal_applications WHERE application_mnemonic = '$IAM_APP_MNEMONIC');"
      kexec_psql_db "$IAM_DB" "DELETE FROM staff_application_permissions WHERE application_id IN (SELECT id FROM staff_portal_applications WHERE application_mnemonic = '$IAM_APP_MNEMONIC');"
      kexec_psql_db "$IAM_DB" "DELETE FROM staff_portal_applications WHERE application_mnemonic = '$IAM_APP_MNEMONIC';"
    fi
  fi
fi

# ========== STEP 6: PVCs ==========
_blue "==> [6/7] Delete PVCs"
if [[ "$NAMESPACE_EXISTS" == true ]]; then
  run "kubectl -n '$NAMESPACE' delete pvc -l 'app.kubernetes.io/instance=$RELEASE' --ignore-not-found"
else
  echo "  (skipped — namespace '$NAMESPACE' not present; any orphan PVs handled in step 7)"
fi

# ========== STEP 7: PVs ==========
_blue "==> [7/7] Delete PVs"
if [[ "$KEEP_PVS" == true ]]; then
  _yellow "  (skipped — --keep-pvs)"
else
  # Only the PVs found in the preview: claimed by this release's PVCs, or
  # labelled with the release.
  pv_all="$OUR_PVS"

  if [[ -z "$pv_all" ]]; then
    echo "  (no PVs to delete)"
  else
    for pv in $pv_all; do
      run "kubectl delete pv '$pv' --ignore-not-found"
    done
  fi
fi

echo
_green "==> Done."
if [[ "$DRY_RUN" == true ]]; then
  _yellow "    (dry-run — nothing was actually changed)"
fi
