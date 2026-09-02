from __future__ import annotations

import pytest
from pydantic import ValidationError

from contract import KeyEntry, ModelEntry, uuid7


def model_entry(**overrides: object) -> dict[str, object]:
    return {
        "model_id": "model",
        "provider_id": "provider",
        "upstream_model": "upstream",
        "input_price_per_mtok": 1,
        "output_price_per_mtok": 2,
        "cache_read_price_per_mtok": 0,
        "cache_write_price_per_mtok": 0,
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


def test_model_capabilities_use_the_policy_vocabulary():
    with pytest.raises(ValidationError):
        ModelEntry.model_validate(model_entry(capabilities=["visionary"]))


def test_inference_key_ids_reject_arbitrary_strings():
    with pytest.raises(ValidationError):
        KeyEntry(key_id="not-a-uuid", org_id=uuid7(), workspace_id=uuid7(), token_hash="hash")
