from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import ValidationError

from contract import BundleManifest, KeyEntry, ModelEntry, uuid7


def model_entry(**overrides: object) -> dict[str, object]:
    return {
        "model_id": "model",
        "provider_id": "provider",
        "upstream_model": "upstream",
        "input_price_per_mtok": "1",
        "output_price_per_mtok": "2",
        "cache_read_price_per_mtok": "0",
        "cache_write_price_per_mtok": "0",
        "context_window": 128000,
        "input_modalities": ["text"],
        "output_modalities": ["text"],
        "capabilities": ["streaming"],
        **overrides,
    }


def test_model_modalities_are_required_bundle_data():
    with pytest.raises(ValidationError):
        ModelEntry.model_validate(model_entry(input_modalities=None))
    with pytest.raises(ValidationError):
        ModelEntry.model_validate(model_entry(output_modalities=[]))


def test_model_prices_are_exact_and_serialize_as_strings():
    model = ModelEntry.model_validate(model_entry())

    assert model.input_price_per_mtok == Decimal(1)
    assert model.model_dump(mode="json")["input_price_per_mtok"] == "1"


def test_model_capabilities_use_the_policy_vocabulary():
    with pytest.raises(ValidationError):
        ModelEntry.model_validate(model_entry(capabilities=["visionary"]))


def test_inference_key_ids_are_opaque_strings():
    key = KeyEntry(key_id="external-key", org_id=uuid7(), workspace_id=uuid7(), user_id=uuid7(), token_hash="hash")
    assert key.key_id == "external-key"


def test_empty_manifest_contains_only_bundle_references():
    assert BundleManifest(bundles=[]).model_dump() == {"bundles": []}


@pytest.mark.parametrize("identity", [{}, {"user_id": None}, {"user_id": "invalid"}])
def test_bundle_keys_require_principal_identity(identity):
    with pytest.raises(ValidationError):
        KeyEntry.model_validate({"key_id": "external", "org_id": uuid7(), "workspace_id": uuid7(), "token_hash": "hash", **identity})
