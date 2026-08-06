from __future__ import annotations

from contract import INFERENCE_TOKEN_PREFIX, token_hash


def test_token_hash_is_stable_sha256_hex():
    assert token_hash("ab-inf-x") == "bea8fcf9768385dab6a9cab2d12a2259289a8f5d7bedccaae05c5caa9ff82f6c"


def test_prefix_ends_with_hyphen():
    assert INFERENCE_TOKEN_PREFIX.endswith("-")
