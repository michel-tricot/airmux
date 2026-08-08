#!/usr/bin/env bash
# Regenerates the CLI's typed API models from the control plane's OpenAPI spec.
# CI regenerates and fails on drift; never hand-edit the output file.
set -euo pipefail
cd "$(dirname "$0")/.."
uv run python - > /tmp/airllm-openapi.json <<'PY'
import json
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from contract import private_key_to_b64
from control_plane.app import create_app
from control_plane.config import BundlePolicy, Settings

key = private_key_to_b64(Ed25519PrivateKey.generate())
settings = Settings(bundle=BundlePolicy(signing_key=key))
print(json.dumps(create_app(settings).openapi()))
PY
uv run datamodel-codegen \
  --input /tmp/airllm-openapi.json \
  --input-file-type openapi \
  --output apps/cli/src/cli/api_models.py \
  --output-model-type pydantic_v2.BaseModel \
  --enum-field-as-literal all \
  --use-union-operator \
  --use-standard-collections \
  --use-schema-description \
  --use-annotated \
  --target-python-version 3.13 \
  --disable-timestamp
uv run ruff format -q apps/cli/src/cli/api_models.py

