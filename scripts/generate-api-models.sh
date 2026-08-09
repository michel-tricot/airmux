#!/usr/bin/env bash
# Regenerates lib/api-models, the typed API models the CLI and any other python client import.
# CI regenerates and fails on drift; never hand-edit the output file.
set -euo pipefail
cd "$(dirname "$0")/.."
uv run datamodel-codegen \
  --input lib/api-spec/openapi.yaml \
  --input-file-type openapi \
  --output lib/api-models/src/api_models/__init__.py \
  --output-model-type pydantic_v2.BaseModel \
  --enum-field-as-literal all \
  --use-union-operator \
  --use-standard-collections \
  --use-schema-description \
  --use-annotated \
  --target-python-version 3.13 \
  --disable-timestamp
uv run ruff format -q lib/api-models/src/api_models/__init__.py
