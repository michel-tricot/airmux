from __future__ import annotations

import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from adapter_support import supported_capabilities, supported_modalities
from build_taxonomy import selected_surface
from evidence import REACHABILITY_PROBE_VERSION, target_fingerprint


def test_adapter_support_is_applied_separately_from_provider_evidence():
    observed = ["streaming", "tools", "json_schema"]

    assert supported_capabilities("anthropic", observed) == ["streaming", "tools"]
    assert supported_capabilities("openai_compatible", observed) == observed


def test_adapter_modalities_are_an_end_to_end_ceiling():
    assert supported_modalities("anthropic", ["text", "image", "audio"]) == ["text", "image"]
    assert supported_modalities("anthropic", ["text", "image"], output=True) == ["text"]


def test_surface_selection_uses_profiles_and_endpoint_evidence():
    provider = {
        "id": "example",
        "ingress": ["oai", "oai_responses"],
        "surfaces": {
            "oai": {
                "endpoint": "chat/completions",
                "auth": "bearer",
                "egress_kind": "openai_compatible",
                "headers": {},
            },
            "oai_responses": {
                "endpoint": "responses",
                "auth": "bearer",
                "egress_kind": "openai_responses",
                "headers": {},
            },
        },
    }
    model = {"id": "new-model"}
    model["endpoint_status"] = {
        endpoint: {
            "version": REACHABILITY_PROBE_VERSION,
            "target": target_fingerprint(provider, model, endpoint, "reachability", REACHABILITY_PROBE_VERSION),
            "outcome": "ok",
        }
        for endpoint in ("chat/completions", "responses")
    }

    surface = selected_surface(provider, model)

    assert surface is not None
    assert surface.egress_kind == "openai_responses"


def test_transient_reachability_failure_does_not_remove_a_route():
    provider = {
        "id": "example",
        "ingress": ["oai"],
        "surfaces": {
            "oai": {
                "endpoint": "chat/completions",
                "auth": "bearer",
                "egress_kind": "openai_compatible",
                "headers": {},
            }
        },
    }
    model = {"id": "new-model"}
    model["endpoint_status"] = {
        "chat/completions": {
            "version": REACHABILITY_PROBE_VERSION,
            "target": target_fingerprint(provider, model, "chat/completions", "reachability", REACHABILITY_PROBE_VERSION),
            "outcome": "http_503",
        }
    }

    assert selected_surface(provider, model) is not None
