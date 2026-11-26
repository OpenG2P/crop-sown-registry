#!/usr/bin/env bash
# Fetch the pinned staff-ui into .app/:
#   1. Clone from GitHub (deps.json) only when .app/package.json is missing
#      — keeps existing .app/node_modules, .next, .env during sync
#   2. Apply overrides/ (create it if missing; add .gitkeep if empty).
#      Then copy ui/staff-ui/.env → .app/.env when it exists.
set -euo pipefail

ui_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
app_dir="$ui_root/.app"
overrides_dir="$ui_root/overrides"
config_path="$ui_root/deps.json"
clone_dir="$ui_root/.app-clone-tmp"

say() { local a= b=; [[ -t 1 ]] && a=$'\033[36m' b=$'\033[0m'; printf '%s%s [staff-ui]%s %s\n' "$a" "$(date +%H:%M:%S)" "$b" "$*"; }
fail() { local a= b=; [[ -t 1 ]] && a=$'\033[31m' b=$'\033[0m'; printf '%s%s [staff-ui]%s %s\n' "$a" "$(date +%H:%M:%S)" "$b" "$*" >&2; exit 1; }

# Skip a path when any component matches the materialize ignore list.
# preserve_env=1 keeps .env (upstream sync). preserve_env=0 copies it (overrides).
should_skip_rel() {
    local rel=$1
    local preserve_env=$2
    local part
    local IFS=/
    read -ra parts <<< "$rel"
    for part in "${parts[@]}"; do
        case "$part" in
            node_modules|.next|.git|.app|.deps-stamp|README.md|Dockerfile|.dockerignore|.gitkeep)
                return 0
                ;;
            .env)
                [[ "$preserve_env" == 1 ]] && return 0
                ;;
        esac
    done
    return 1
}

copy_filtered() {
    local src=$1
    local dest=$2
    local preserve_env=$3
    local path rel
    mkdir -p "$dest"
    while IFS= read -r -d '' path; do
        rel=${path#"$src"/}
        should_skip_rel "$rel" "$preserve_env" && continue
        if [[ -d "$path" && ! -L "$path" ]]; then
            mkdir -p "$dest/$rel"
        else
            mkdir -p "$dest/$(dirname "$rel")"
            cp -a "$path" "$dest/$rel"
        fi
    done < <(find "$src" -mindepth 1 -print0)
}

wipe_app_except_preserved() {
    local entry base
    shopt -s dotglob nullglob
    for entry in "$app_dir"/*; do
        base=$(basename "$entry")
        case "$base" in
            node_modules|.next|.git|.app|.env|.deps-stamp|README.md|Dockerfile|.dockerignore|.gitkeep)
                continue
                ;;
        esac
        rm -rf "$entry"
    done
    shopt -u dotglob nullglob
}

sync_into_app() {
    local src_root=$1
    [[ -f "$src_root/package.json" ]] || fail "No package.json at $src_root"
    mkdir -p "$app_dir"
    wipe_app_except_preserved
    copy_filtered "$src_root" "$app_dir" 1
}

fetch_staff_ui() {
    [[ -f "$config_path" ]] || fail "Missing $config_path"

    local repo ref sub_path
    local cfg
    cfg=$(node -e '
        const c = require(process.argv[1]);
        if (!c.repo || !c.ref || !c.path) process.exit(2);
        process.stdout.write([c.repo, c.ref, c.path].join("\n"));
    ' "$config_path") || fail "repo, ref, and path are required in deps.json"
    repo=${cfg%%$'\n'*}
    ref=${cfg#*$'\n'}
    ref=${ref%%$'\n'*}
    sub_path=${cfg##*$'\n'}
    if [[ -z "$repo" || -z "$ref" || -z "$sub_path" || "$repo" == "$ref" || "$ref" == "$sub_path" ]]; then
        fail "repo, ref, and path are required in deps.json"
    fi

    rm -rf "$clone_dir"
    local log
    log=$(mktemp)
    say "Cloning ${repo} @ ${ref} (${sub_path})…"
    if ! git clone --quiet --depth 1 --filter=blob:none --sparse --branch "$ref" "$repo" "$clone_dir" >"$log" 2>&1; then
        cat "$log" >&2
        rm -f "$log"
        fail "git clone failed"
    fi
    if ! git -C "$clone_dir" sparse-checkout set "$sub_path" >"$log" 2>&1; then
        cat "$log" >&2
        rm -f "$log"
        fail "git sparse-checkout failed"
    fi
    rm -f "$log"

    sync_into_app "$clone_dir/$sub_path"
    rm -rf "$clone_dir"
    say "Cloned into .app/"
}

apply_overrides() {
    if [[ ! -d "$overrides_dir" ]]; then
        mkdir -p "$overrides_dir"
        say "Created overrides/"
    fi
    shopt -s nullglob dotglob
    local entries=("$overrides_dir"/*)
    shopt -u nullglob dotglob
    if ((${#entries[@]} == 0)); then
        : > "$overrides_dir/.gitkeep"
        say "Added overrides/.gitkeep"
    fi
    say "Applying overrides/…"
    copy_filtered "$overrides_dir" "$app_dir" 0
    if [[ -f "$ui_root/.env" ]]; then
        cp "$ui_root/.env" "$app_dir/.env"
    fi
    say "Applied overrides/"
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
    if [[ -f "$app_dir/package.json" ]]; then
        say ".app/ already present — skip clone"
    else
        fetch_staff_ui
    fi
    apply_overrides
fi
