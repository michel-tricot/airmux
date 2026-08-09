from __future__ import annotations

from contract import INFERENCE_TOKEN_PREFIX, token_hash


def test_token_hash_is_stable_sha256_hex():
    assert token_hash("sk-inf-x") == "4e7fab6a94d14727e73bbdd68f332dbc9ab6cb040e488a5d603d8a1a760987bf"


def test_prefix_ends_with_hyphen():
    assert INFERENCE_TOKEN_PREFIX.endswith("-")
