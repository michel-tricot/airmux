from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from contract import (
    INFERENCE_TOKEN_PREFIX,
    BundleV1,
    Catalog,
    CredentialEntry,
    KeyEntry,
    SecretPurpose,
    SecretRef,
    sign_bundle,
    token_hash,
    uuid7,
)
from data_plane.config import BundleConfig, Config, ControlPlaneLink, EventsConfig

NOW = datetime.now(tz=UTC)
ORG = uuid7()
WORKSPACE = uuid7()

UNUSED_PUBLIC_KEY = Ed25519PrivateKey.generate().public_key()


def make_credential(service="p1", name="default", org=ORG, **scope) -> CredentialEntry:
    """A credential entry naming a secret.

    scope takes workspace, priority, version and secret_id. Passing secret_id describes the same
    credential twice, which is what a rotation looks like from the data plane.
    """
    ref = SecretRef(
        purpose=SecretPurpose.provider,
        service=service,
        name=name,
        secret_id=scope.get("secret_id") or uuid7(),
        org_id=org,
        workspace_id=scope.get("workspace"),
    )
    return CredentialEntry(ref=ref, priority=scope.get("priority", 100), version=scope.get("version", 1))


def make_key(key_id="k-dev", org=ORG, workspace=WORKSPACE):
    """A deterministic opaque token and its bundle entry; the token derives from the key_id so tests stay reproducible."""
    token = f"{INFERENCE_TOKEN_PREFIX}secret-{key_id}"
    return token, KeyEntry(key_id=key_id, org_id=org, workspace_id=workspace, token_hash=token_hash(token))


def make_bundle(keys=(), catalog=None, org=ORG):
    return BundleV1(
        bundle_id=uuid4(),
        org_id=org,
        issued_at=NOW,
        expires_at=NOW + timedelta(hours=24),
        keys=list(keys),
        catalog=catalog or Catalog(providers=[], models=[]),
    )


def make_signed(private_key, key_ids=("k1",), org=ORG):
    keys = [make_key(k, org)[1] for k in key_ids]
    return sign_bundle(make_bundle(keys=keys, org=org), private_key, "k1")


def make_config(tmp_path, backend="sqlite") -> Config:
    return Config(
        control_plane=ControlPlaneLink(url="http://cp.test", token="dp-token"),
        bundle=BundleConfig(public_key=UNUSED_PUBLIC_KEY, cache_dir=tmp_path),
        events=EventsConfig(backend=backend),
    )
