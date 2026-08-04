from __future__ import annotations

import yaml

from cli.main import BootstrapSpec


def test_minimal_spec_gets_defaults():
    spec = BootstrapSpec.model_validate(yaml.safe_load("org: o1"))
    assert spec.providers == []
    assert spec.models == []
    assert [k.allowed_models for k in spec.keys] == [["*"]]


def test_full_spec_parses():
    doc = """
org: o1
providers:
  - provider_id: openai
    base_url: https://api.openai.com/v1
    credential_ref: env:OPENAI_API_KEY
models:
  - model_id: gpt-4o-mini
    provider_id: openai
keys:
  - allowed_models: ["gpt-4o-mini"]
  - allowed_models: ["*"]
"""
    spec = BootstrapSpec.model_validate(yaml.safe_load(doc))
    assert spec.providers[0].kind == "openai_compatible"
    assert spec.models[0].upstream_model == ""
    assert spec.models[0].capabilities == ["streaming", "tools"]
    assert len(spec.keys) == 2
