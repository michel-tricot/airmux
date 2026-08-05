from __future__ import annotations

from datetime import UTC, datetime

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from contract import INFERENCE_TOKEN_PREFIX, mint_inference_token, verify_inference_token
from control_plane.tokens import MANAGEMENT_TOKEN_PREFIX, mint_management_token, verify_management_token

NOW = datetime(2026, 8, 4, tzinfo=UTC)


def test_management_token_instance_round_trip():
    key = Ed25519PrivateKey.generate()
    token = mint_management_token(None, key, NOW, "mt-root")
    claims = verify_management_token(token, key.public_key())
    assert claims is not None
    assert claims.org_id is None
    assert claims.token_id == "mt-root"


def test_management_token_org_round_trip():
    key = Ed25519PrivateKey.generate()
    token = mint_management_token("org-dev", key, NOW, "mt-1")
    claims = verify_management_token(token, key.public_key())
    assert claims is not None
    assert claims.org_id == "org-dev"
    assert claims.token_id == "mt-1"


def test_prefix_keeps_the_jwt_scannable():
    key = Ed25519PrivateKey.generate()
    assert mint_management_token("org-dev", key, NOW, "mt-1").startswith(f"{MANAGEMENT_TOKEN_PREFIX}eyJ")
    assert MANAGEMENT_TOKEN_PREFIX.endswith("-")


def test_token_kinds_are_not_interchangeable():
    key = Ed25519PrivateKey.generate()
    inference = mint_inference_token("k-1", "org-dev", key, NOW)
    management = mint_management_token("org-dev", key, NOW, "mt-1")
    assert verify_management_token(inference, key.public_key()) is None
    assert verify_inference_token(management, key.public_key()) is None


def test_reprefixed_token_is_rejected():
    key = Ed25519PrivateKey.generate()
    inference = mint_inference_token("k-1", "org-dev", key, NOW)
    forged = MANAGEMENT_TOKEN_PREFIX + inference.removeprefix(INFERENCE_TOKEN_PREFIX)
    assert verify_management_token(forged, key.public_key()) is None


def test_wrong_key_and_garbage_are_rejected():
    key = Ed25519PrivateKey.generate()
    other = Ed25519PrivateKey.generate()
    token = mint_management_token(None, key, NOW, "mt-root")
    assert verify_management_token(token, other.public_key()) is None
    assert verify_management_token("ab-mgmt-not-a-jwt", key.public_key()) is None
    assert verify_management_token("", key.public_key()) is None
