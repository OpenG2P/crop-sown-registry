#!/usr/bin/env bash
# Bump the pinned openg2p-registry (registry-platform) version this variant
# extends — in BOTH the Dockerfiles (ARG RP_VERSION) and the Helm chart
# dependency — atomically, so the two can never drift.
#
# WHY "SAFE" LATEST
#   A variant pins ONE version used for the Docker base images AND the chart
#   dependency. registry-platform publishes both in lockstep per commit, but the
#   Helm index regenerates AFTER the images are pushed, so there is a window where
#   the newest image tag has no matching chart yet (or a chart step lagged/failed).
#   Picking an image-only version would write a chart dependency that does not
#   resolve. So "latest" here means the highest 0.0.0-develop.N present in BOTH
#   the Helm index AND the container registry. An explicit version is likewise
#   verified to exist in both before anything is written.
#
# Requires: bash, curl, python3, helm. Run from the repo root.
set -euo pipefail

# ── repo-specific: the chart dir this variant ships ───────────────────────────
# The chart dir is the only per-repo value; everything else is derived.
CHART_DIR="helm/openg2p-crop-sown-registry"

REGISTRY_CHART="openg2p-registry"

# registry-platform publishes its chart to the openg2p-helm Pages index and its
# images to Docker Hub. Both are public, so every read below is anonymous.
# To eyeball a release by hand instead:
#   https://openg2p.github.io/versions/registry-platform/CHANGELOG.html
#   https://hub.docker.com/u/openg2p
HELM_INDEX="https://openg2p.github.io/openg2p-helm/index.yaml"
HUB_API="https://hub.docker.com/v2/repositories/openg2p"
# One representative platform image; all are published together at the same tag.
PROBE_IMAGE="sanity-tests"

die() { echo "ERROR: $*" >&2; exit 1; }
note() { echo "  $*"; }

usage() {
  cat <<EOF
Bump the pinned openg2p-registry version (Dockerfiles' ARG RP_VERSION + the Helm
chart dependency) atomically, so images and chart never drift.

Usage:
  ./scripts/bump-rp-version.sh                 Bump to the latest SAFE version.
  ./scripts/bump-rp-version.sh <version>       Bump to a specific version.
  ./scripts/bump-rp-version.sh -n              Show the latest SAFE version;
  ./scripts/bump-rp-version.sh -n <version>    check a version — write NOTHING.
  ./scripts/bump-rp-version.sh -h              This help.

Options:
  -n, --check, --dry-run   Resolve/validate and print, but do not modify any file.
  -h, --help               Show this help.

"Latest SAFE" = the highest 0.0.0-develop.N present in BOTH the GitLab Helm
registry and registry-platform's container registry (an image-only tag whose
chart has not published yet is skipped). A specific <version> is accepted only
if it exists in both.

Examples:
  ./scripts/bump-rp-version.sh -n              # what would 'latest' pick?
  ./scripts/bump-rp-version.sh                 # take it
  ./scripts/bump-rp-version.sh 0.0.0-develop.296
EOF
}

# ── args ──────────────────────────────────────────────────────────────────────
CHECK_ONLY=false
VERSION_ARG=""
while [ $# -gt 0 ]; do
  case "$1" in
    -h|--help)              usage; exit 0 ;;
    -n|--check|--dry-run)   CHECK_ONLY=true; shift ;;
    -*)                     die "unknown option '$1' (see --help)" ;;
    *)                      [ -z "$VERSION_ARG" ] || die "unexpected extra argument '$1'"; VERSION_ARG="$1"; shift ;;
  esac
done

command -v curl    >/dev/null || die "curl is required"
command -v python3 >/dev/null || die "python3 is required"
command -v helm    >/dev/null || die "helm is required"
[ -d "$CHART_DIR" ] || die "run from the repo root ($CHART_DIR not found)"

# ── discover published versions ───────────────────────────────────────────────
chart_versions() {
  curl -fsSL "$HELM_INDEX" 2>/dev/null \
    | grep -oE "${REGISTRY_CHART}-[0-9][^ ]*\.tgz" \
    | sed -E "s/^${REGISTRY_CHART}-//; s/\.tgz$//" | sort -u
}

image_versions() {
  # Docker Hub addresses repositories by name, so no id lookup is needed.
  local repo_id="openg2p-registry-${PROBE_IMAGE}"

  # paginate tags (100/page is the max)
  local page=1 body names
  while :; do
    body=$(curl -fsSL "${HUB_API}/${repo_id}/tags?page_size=100&page=${page}" 2>/dev/null) || break
    names=$(printf '%s' "$body" | python3 -c "import sys,json; [print(t['name']) for t in json.load(sys.stdin).get('results',[])]" 2>/dev/null) || break
    [ -n "$names" ] || break
    printf '%s\n' "$names"
    page=$((page+1))
  done | sort -u
}

# highest develop version present in BOTH lists (numeric on the .N suffix)
latest_safe() {
  python3 - "$@" <<'PY'
import sys
chart=set(l.strip() for l in open(sys.argv[1]) if l.strip())
image=set(l.strip() for l in open(sys.argv[2]) if l.strip())
both=[v for v in chart & image if v.startswith("0.0.0-develop.")]
if not both:
    sys.exit("no 0.0.0-develop.N version exists in BOTH the Helm registry and the container registry")
both.sort(key=lambda v:int(v.rsplit(".",1)[1]))
print(both[-1])
PY
}

TMP=$(mktemp -d); trap 'rm -rf "$TMP"' EXIT
echo "Resolving published openg2p-registry versions…"
chart_versions > "$TMP/chart" || die "could not read the Helm index ($HELM_INDEX)"
image_versions > "$TMP/image" || die "could not read registry-platform's container registry"
[ -s "$TMP/chart" ] || die "no ${REGISTRY_CHART} versions in the Helm index"
[ -s "$TMP/image" ] || die "no tags for the '${PROBE_IMAGE}' image in registry-platform's container registry"

if [ -n "$VERSION_ARG" ]; then
  VERSION="$VERSION_ARG"
  grep -qxF "$VERSION" "$TMP/chart" || die "version '$VERSION' has no published ${REGISTRY_CHART} chart"
  grep -qxF "$VERSION" "$TMP/image" || die "version '$VERSION' has no published '${PROBE_IMAGE}' image"
  note "requested version: $VERSION (verified in chart + images)"
else
  VERSION=$(latest_safe "$TMP/chart" "$TMP/image") || die "$VERSION"
  note "latest safe develop version (in chart + images): $VERSION"
fi

# ── current pins ──────────────────────────────────────────────────────────────
CUR_CHART=$(python3 - "$CHART_DIR/Chart.yaml" <<'PY'
import re,sys
s=open(sys.argv[1]).read()
m=re.search(r'name:\s*openg2p-registry\b.*?version:\s*(\S+)', s, re.S)
print(m.group(1) if m else "")
PY
)
CUR_DOCKER=$(grep -hoE 'ARG RP_VERSION=\S+' docker/*/Dockerfile | sed 's/ARG RP_VERSION=//' | sort -u | tr '\n' ',' | sed 's/,$//')
note "current: chart=$CUR_CHART  dockerfiles=$CUR_DOCKER"

if [ "$CHECK_ONLY" = "true" ]; then
  if [ "$CUR_CHART" = "$VERSION" ] && [ "$CUR_DOCKER" = "$VERSION" ]; then
    echo "  already at $VERSION — no bump needed."
  else
    echo "  would bump: ${CUR_CHART} -> ${VERSION}   (run without -n to apply)"
  fi
  exit 0
fi

if [ "$CUR_CHART" = "$VERSION" ] && [ "$CUR_DOCKER" = "$VERSION" ]; then
  note "already at $VERSION — nothing to do."
  exit 0
fi

# ── rewrite (atomic: same value to every Dockerfile + the chart dep) ──────────
for f in docker/*/Dockerfile; do
  grep -q 'ARG RP_VERSION=' "$f" || continue
  python3 - "$f" "$VERSION" <<'PY'
import re,sys
f,v=sys.argv[1],sys.argv[2]
s=open(f).read()
s=re.sub(r'ARG RP_VERSION=\S+', f'ARG RP_VERSION={v}', s)
open(f,'w').write(s)
PY
done

python3 - "$CHART_DIR/Chart.yaml" "$VERSION" <<'PY'
import re,sys
f,v=sys.argv[1],sys.argv[2]
s=open(f).read()
# rewrite the version ONLY inside the openg2p-registry dependency block
def repl(m): return re.sub(r'(version:\s*)\S+', r'\g<1>'+v, m.group(0), count=1)
s=re.sub(r'-\s*name:\s*openg2p-registry\b.*?(?=\n\s*-\s|\n\S|\Z)', repl, s, count=1, flags=re.S)
open(f,'w').write(s)
PY

# refresh the dependency lock so it matches the new pin
echo "Updating the chart dependency lock…"
helm repo add openg2p-charts "${HELM_INDEX%/index.yaml}" >/dev/null 2>&1 || true
helm repo update openg2p-charts >/dev/null 2>&1 || true
helm dependency update "$CHART_DIR" >/dev/null 2>&1 || die "helm dependency update failed for $VERSION"

# ── verify + report ───────────────────────────────────────────────────────────
NEW_CHART=$(python3 - "$CHART_DIR/Chart.yaml" <<'PY'
import re,sys
m=re.search(r'name:\s*openg2p-registry\b.*?version:\s*(\S+)', open(sys.argv[1]).read(), re.S)
print(m.group(1) if m else "")
PY
)
NEW_DOCKER=$(grep -hoE 'ARG RP_VERSION=\S+' docker/*/Dockerfile | sed 's/ARG RP_VERSION=//' | sort -u | tr '\n' ',' | sed 's/,$//')
[ "$NEW_CHART" = "$VERSION" ] && [ "$NEW_DOCKER" = "$VERSION" ] \
  || die "post-write check failed: chart=$NEW_CHART dockerfiles=$NEW_DOCKER (expected $VERSION)"

echo ""
echo "Bumped openg2p-registry pin: ${CUR_CHART} -> ${VERSION}"
echo "  Dockerfiles + chart dependency now aligned at ${VERSION}."
echo "  Review, then commit:"
echo "    git add docker helm/${CHART_DIR#helm/}/Chart.yaml && git commit"
