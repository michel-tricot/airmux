from __future__ import annotations

from datetime import UTC, datetime

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from contract import INFERENCE_TOKEN_PREFIX, mint_inference_token, verify_inference_token

NOW = datetime(2026, 8, 4, tzinfo=UTC)


def test_inference_token_round_trip():
    key = Ed25519PrivateKey.generate()
    token = mint_inference_token("k-1", "org-dev", key, NOW)
    claims = verify_inference_token(token, key.public_key())
    assert claims is not None
    assert claims.key_id == "k-1"
    assert claims.org_id == "org-dev"


def test_prefix_keeps_the_jwt_scannable():
    key = Ed25519PrivateKey.generate()
    assert mint_inference_token("k-1", "org-dev", key, NOW).startswith(f"{INFERENCE_TOKEN_PREFIX}eyJ")
    assert INFERENCE_TOKEN_PREFIX.endswith("-")


def test_wrong_key_and_garbage_are_rejected():
    key = Ed25519PrivateKey.generate()
    other = Ed25519PrivateKey.generate()
    token = mint_inference_token("k-1", "org-dev", key, NOW)
    assert verify_inference_token(token, other.public_key()) is None
    assert verify_inference_token("ab-inf-not-a-jwt", key.public_key()) is None
    assert verify_inference_token(token.removeprefix(INFERENCE_TOKEN_PREFIX), key.public_key()) is None
    assert verify_inference_token("", key.public_key()) is None
