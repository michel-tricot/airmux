#!/usr/bin/env bash
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
output="${1:-$root/dist}"
mkdir -p "$output"
output="$(cd "$output" && pwd)"
stage="$(mktemp -d "${TMPDIR:-/tmp}/airmux-build.XXXXXX")"
trap 'rm -rf "$stage"' EXIT

project="$stage/packaging/airmux"
mkdir -p "$project/src"
cp -R "$root/packaging/airmux/." "$project"
cp "$root/VERSION" "$stage/VERSION"
cp "$root/LICENSE" "$project/LICENSE"
cp "$root/README.md" "$project/README.md"
cp -R "$root/lib/api-models/src/api_models" "$project/src/api_models"
cp -R "$root/apps/cli/src/cli" "$project/src/cli"
cp -R "$root/lib/contract/src/contract" "$project/src/contract"
cp -R "$root/lib/runtime/src/airmux_runtime" "$project/src/airmux_runtime"
cp -R "$root/apps/control-plane/src/control_plane" "$project/src/control_plane"
cp -R "$root/apps/data-plane/src/data_plane" "$project/src/data_plane"

uv build --out-dir "$output" "$project"
