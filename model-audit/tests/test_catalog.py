from __future__ import annotations

import json

import yaml

from model_audit.catalog import load_catalog


def test_catalog_targets_carry_the_applied_gateway_egress(tmp_path):
    (tmp_path / "models").mkdir()
    (tmp_path / "providers.yml").write_text(
        yaml.safe_dump(
            {
                "providers": [
                    {
                        "id": "openai",
                        "base_url": "https://api.openai.com/v1",
                        "env_var": "OPENAI_API_KEY",
                        "ingress": ["oai", "oai_responses"],
                        "auth": ["bearer"],
                        "param_aliases": {"max_tokens": "max_completion_tokens"},
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "models" / "openai.json").write_text(
        json.dumps({"models": [{"id": "gpt-test", "context_length": 1000}, {"id": "not-routable", "context_length": 1000}]}),
        encoding="utf-8",
    )
    (tmp_path / "taxonomy.yml").write_text(
        yaml.safe_dump(
            {
                "providers": [{"provider_id": "openai", "kind": "openai_compatible"}],
                "models": [
                    {
                        "model_id": "openai/gpt-test",
                        "provider_id": "openai",
                        "egress_kind": "openai_responses",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    catalog = load_catalog(tmp_path)

    assert [(target.model_id, target.surface_id, target.gateway_egress_kind) for target in catalog.targets] == [
        ("openai/gpt-test", "oai", "openai_responses"),
        ("openai/gpt-test", "oai_responses", "openai_responses"),
    ]
    assert all(target.param_aliases == {"max_tokens": "max_completion_tokens"} for target in catalog.targets)
