#!/usr/bin/env bash
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
output="${1:-$root/dist}"
mkdir -p "$output"
output="$(cd "$output" && pwd)"
stage="$(mktemp -d "${TMPDIR:-/tmp}/airmux-build.XXXXXX")"
trap 'rm -rf "$stage"' EXIT

cp -R "$root/packaging/airmux/." "$stage"
cp "$root/LICENSE" "$stage/LICENSE"
cp "$root/README.md" "$stage/README.md"
mkdir -p "$stage/src"
cp -R "$root/lib/api-models/src/api_models" "$stage/src/api_models"
cp -R "$root/apps/cli/src/cli" "$stage/src/cli"
cp -R "$root/lib/contract/src/contract" "$stage/src/contract"
cp -R "$root/apps/control-plane/src/control_plane" "$stage/src/control_plane"
cp -R "$root/apps/data-plane/src/data_plane" "$stage/src/data_plane"

uv build --out-dir "$output" "$stage"
