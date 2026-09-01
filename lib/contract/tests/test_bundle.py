from __future__ import annotations

import pytest
from pydantic import ValidationError

from contract import ModelEntry


def test_model_modalities_are_required_bundle_data():
    with pytest.raises(ValidationError):
        ModelEntry.model_validate(
            {
                "model_id": "model",
                "provider_id": "provider",
                "upstream_model": "upstream",
                "input_price_per_mtok": 1,
                "output_price_per_mtok": 2,
                "cache_read_price_per_mtok": 0,
                "cache_write_price_per_mtok": 0,
                "context_window": 128000,
                "capabilities": ["streaming"],
            }
        )
