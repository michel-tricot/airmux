from __future__ import annotations

import pytest

from data_plane.adapters import REGISTRY


@pytest.mark.parametrize("kind", sorted(REGISTRY))
def test_adapter_is_registered_with_matching_kind(kind):
    assert REGISTRY[kind].kind == kind


def test_both_adapters_discovered():
    assert {"openai_compatible", "anthropic"} <= set(REGISTRY)
