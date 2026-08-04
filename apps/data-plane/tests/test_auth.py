from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from contract import BundleV1, Catalog, KeyEntry, mint_api_token
from data_plane.auth import authenticate, index_keys

NOW = datetime.now(tz=UTC)


def make_bundle(keys, revocations=()):
    return BundleV1(
        bundle_id=uuid4(),
        org_id="org-a",
        issued_at=NOW,
        expires_at=NOW + timedelta(hours=24),
        keys=keys,
        revocations=list(revocations),
        catalog=Catalog(providers=[], models=[]),
    )


def test_valid_token_authenticates():
    private_key = Ed25519PrivateKey.generate()
    bundle = make_bundle([KeyEntry(key_id="k1", org_id="org-a", allowed_models=["*"])])
    token = mint_api_token("k1", "org-a", private_key, NOW)
    key = authenticate(token, private_key.public_key(), index_keys(bundle), frozenset(bundle.revocations))
    assert key is not None
    assert key.key_id == "k1"


def test_token_signed_by_other_key_rejected():
    private_key = Ed25519PrivateKey.generate()
    bundle = make_bundle([KeyEntry(key_id="k1", org_id="org-a", allowed_models=["*"])])
    forged = mint_api_token("k1", "org-a", Ed25519PrivateKey.generate(), NOW)
    assert authenticate(forged, private_key.public_key(), index_keys(bundle), frozenset()) is None


def test_revoked_key_rejected_despite_valid_signature():
    private_key = Ed25519PrivateKey.generate()
    bundle = make_bundle([KeyEntry(key_id="k1", org_id="org-a", allowed_models=["*"])], revocations=["k1"])
    token = mint_api_token("k1", "org-a", private_key, NOW)
    assert authenticate(token, private_key.public_key(), index_keys(bundle), frozenset(bundle.revocations)) is None


def test_unknown_key_id_rejected():
    private_key = Ed25519PrivateKey.generate()
    bundle = make_bundle([])
    token = mint_api_token("ghost", "org-a", private_key, NOW)
    assert authenticate(token, private_key.public_key(), index_keys(bundle), frozenset()) is None


def test_garbage_token_rejected():
    private_key = Ed25519PrivateKey.generate()
    bundle = make_bundle([KeyEntry(key_id="k1", org_id="org-a", allowed_models=["*"])])
    assert authenticate("not-a-jwt", private_key.public_key(), index_keys(bundle), frozenset()) is None
