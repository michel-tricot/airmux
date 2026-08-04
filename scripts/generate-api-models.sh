#!/usr/bin/env bash
# Regenerates the CLI's typed API models from the control plane's OpenAPI spec.
# CI regenerates and fails on drift; never hand-edit the output file.
set -euo pipefail
cd "$(dirname "$0")/.."
uv run python -c "import json; from control_plane.app import app; print(json.dumps(app.openapi()))" > /tmp/airllm-openapi.json
uv run datamodel-codegen \
  --input /tmp/airllm-openapi.json \
  --input-file-type openapi \
  --output apps/cli/src/cli/api_models.py \
  --output-model-type pydantic_v2.BaseModel \
  --enum-field-as-literal all \
  --use-union-operator \
  --use-standard-collections \
  --use-schema-description \
  --target-python-version 3.13 \
  --disable-timestamp
uv run ruff format -q apps/cli/src/cli/api_models.py

