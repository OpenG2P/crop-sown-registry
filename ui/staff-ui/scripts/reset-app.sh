#!/usr/bin/env bash
# Remove .app/ and build it again: clone, overrides, .env, dependencies.
set -euo pipefail

ui_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
app_dir="$ui_root/.app"

say() { local a= b=; [[ -t 1 ]] && a=$'\033[36m' b=$'\033[0m'; printf '%s%s [staff-ui]%s %s\n' "$a" "$(date +%H:%M:%S)" "$b" "$*"; }

if [[ -d "$app_dir" ]]; then
    say "Removing .app/…"
    rm -rf "$app_dir"
    say "Removed .app/"
else
    say ".app/ is already absent"
fi

bash "$ui_root/scripts/materialize-staff-ui.sh"
bash "$ui_root/scripts/ensure-app-deps.sh"
