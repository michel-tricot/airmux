#!/usr/bin/env bash
# Re-exports the committed OpenAPI spec from the control plane routes.
# CI re-exports and fails on drift; never hand-edit the spec.
set -euo pipefail
cd "$(dirname "$0")/.."
uv run tokkeeper-control-plane openapi --out lib/api-spec/openapi.yaml
