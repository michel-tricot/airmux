#!/usr/bin/env bash
# Re-exports the committed completion schemas from the data plane's owned definition.
# CI re-exports and fails on drift; never hand-edit them.
set -euo pipefail
cd "$(dirname "$0")/.."
uv run airmux gateway schema --out taxonomy/schemas/completion
