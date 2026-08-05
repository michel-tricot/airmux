from __future__ import annotations

from functools import partial

import jwt
from conftest import NOW
from conftest import make_bundle as _make_bundle
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from contract import KeyEntry, mint_inference_token
from data_plane.auth import authenticate, index_keys

make_bundle = partial(_make_bundle, org="org-a")


def test_valid_token_authenticates():
    private_key = Ed25519PrivateKey.generate()
    bundle = make_bundle([KeyEntry(key_id="k1", org_id="org-a", allowed_models=["*"])])
    token = mint_inference_token("k1", "org-a", private_key, NOW)
    key = authenticate(token, private_key.public_key(), index_keys(bundle), frozenset(bundle.revocations))
    assert key is not None
    assert key.key_id == "k1"


def test_token_signed_by_other_key_rejected():
    private_key = Ed25519PrivateKey.generate()
    bundle = make_bundle([KeyEntry(key_id="k1", org_id="org-a", allowed_models=["*"])])
    forged = mint_inference_token("k1", "org-a", Ed25519PrivateKey.generate(), NOW)
    assert authenticate(forged, private_key.public_key(), index_keys(bundle), frozenset()) is None


def test_revoked_key_rejected_despite_valid_signature():
    private_key = Ed25519PrivateKey.generate()
    bundle = make_bundle([KeyEntry(key_id="k1", org_id="org-a", allowed_models=["*"])], revocations=["k1"])
    token = mint_inference_token("k1", "org-a", private_key, NOW)
    assert authenticate(token, private_key.public_key(), index_keys(bundle), frozenset(bundle.revocations)) is None


def test_unknown_key_id_rejected():
    private_key = Ed25519PrivateKey.generate()
    bundle = make_bundle([])
    token = mint_inference_token("ghost", "org-a", private_key, NOW)
    assert authenticate(token, private_key.public_key(), index_keys(bundle), frozenset()) is None


def test_management_shaped_token_rejected_for_inference():
    private_key = Ed25519PrivateKey.generate()
    bundle = make_bundle([KeyEntry(key_id="k1", org_id="org-a", allowed_models=["*"])])
    payload = {"use": "management", "jti": "mt-1", "org": "org-a", "iat": int(NOW.timestamp())}
    token = "ab-mgmt-" + jwt.encode(payload, private_key, algorithm="EdDSA")
    assert authenticate(token, private_key.public_key(), index_keys(bundle), frozenset()) is None


def test_garbage_token_rejected():
    private_key = Ed25519PrivateKey.generate()
    bundle = make_bundle([KeyEntry(key_id="k1", org_id="org-a", allowed_models=["*"])])
    assert authenticate("not-a-jwt", private_key.public_key(), index_keys(bundle), frozenset()) is None
