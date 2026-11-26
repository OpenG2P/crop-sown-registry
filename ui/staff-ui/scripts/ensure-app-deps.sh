#!/usr/bin/env bash
# Ensure .app has node_modules matching package-lock.json.
set -euo pipefail

ui_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
app_dir="$ui_root/.app"
modules="$app_dir/node_modules"
lockfile="$app_dir/package-lock.json"
stamp="$app_dir/.deps-stamp"

say() { local a= b=; [[ -t 1 ]] && a=$'\033[36m' b=$'\033[0m'; printf '%s%s [staff-ui]%s %s\n' "$a" "$(date +%H:%M:%S)" "$b" "$*"; }
fail() { local a= b=; [[ -t 1 ]] && a=$'\033[31m' b=$'\033[0m'; printf '%s%s [staff-ui]%s %s\n' "$a" "$(date +%H:%M:%S)" "$b" "$*" >&2; exit 1; }

if [[ ! -f "$app_dir/package.json" ]]; then
    fail "Missing .app/ — clone did not produce a package.json"
fi

file_sha256() {
    if command -v sha256sum >/dev/null 2>&1; then
        sha256sum "$1" | awk '{print $1}'
    else
        shasum -a 256 "$1" | awk '{print $1}'
    fi
}

expected=""
[[ -f "$lockfile" ]] && expected=$(file_sha256 "$lockfile")
current=""
[[ -f "$stamp" ]] && current=$(tr -d '[:space:]' < "$stamp")

if [[ -d "$modules" && -n "$expected" && "$current" == "$expected" ]]; then
    say "Dependencies already installed"
    exit 0
fi

say "Installing dependencies…"
( cd "$app_dir" && npm ci --no-audit --no-fund --loglevel=error )
say "Dependencies installed"
if [[ -n "$expected" ]]; then
    printf '%s' "$expected" > "$stamp"
fi
