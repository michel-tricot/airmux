"""A bundle written by hand, for a data plane with no control plane.

The spec compiles to the same BundleV1 the poller fetches, and enters through the same
admit(). The request path never learns the source. There is no signature: the file is
trusted because the operator owns the filesystem it sits on."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING
from uuid import UUID, uuid5

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from contract import BundleV1, Catalog, CredentialEntry, KeyEntry, ModelEntry, ProviderEntry, SecretPurpose, SecretRef, token_hash
from data_plane.tasks import run_periodic

if TYPE_CHECKING:
    from pathlib import Path

    from data_plane.bundle.config import LocalBundleConfig
    from data_plane.bundle.holder import BundleHolder

logger = logging.getLogger("data_plane")

LOCAL_ORG = UUID(int=0)
LOCAL_WORKSPACE = UUID(int=0)
LIFETIME = timedelta(days=36500)  # a local bundle does not expire; freshness is the file's mtime

# Fixed namespace for uuid5, so ids are stable across reloads. A stable secret_id keeps the
# credential resolver cache warm; a content-derived bundle_id changes only when the file does.
_NAMESPACE = UUID("6c1a8f7e-4b62-4b8e-9f0d-2a52e07f1a11")


class LocalBundleSpec(BaseModel):
    """What an operator writes. Providers and models are the contract entries themselves, so
    provider profiles work here exactly as they do in a compiled bundle.

    Keys are plaintext tokens; the compile step hashes them. Credentials are synthesized: one
    platform credential per provider, which the env store resolves as {PROVIDER}_API_KEY."""

    model_config = ConfigDict(extra="forbid")

    keys: list[str] = Field(min_length=1)
    providers: list[ProviderEntry]
    models: list[ModelEntry]


def compile_local(spec: LocalBundleSpec, raw: str, now: datetime) -> BundleV1:
    """Pure, like the control plane's compiler: all nondeterminism comes in through the arguments."""
    keys = [
        KeyEntry(key_id=f"local-{position}", org_id=LOCAL_ORG, workspace_id=LOCAL_WORKSPACE, token_hash=token_hash(token))
        for position, token in enumerate(spec.keys)
    ]
    credentials = [
        CredentialEntry(
            ref=SecretRef(
                purpose=SecretPurpose.provider,
                service=provider.provider_id,
                name="default",
                secret_id=uuid5(_NAMESPACE, provider.provider_id),
                org_id=None,
                workspace_id=None,
            ),
            priority=100,
            version=1,
        )
        for provider in spec.providers
    ]
    return BundleV1(
        bundle_id=uuid5(_NAMESPACE, raw),
        org_id=LOCAL_ORG,
        issued_at=now,
        expires_at=now + LIFETIME,
        keys=keys,
        catalog=Catalog(providers=spec.providers, models=spec.models, credentials=credentials),
    )


def load_local(path: Path, now: datetime) -> BundleV1:
    raw = path.read_text(encoding="utf-8")
    spec = LocalBundleSpec.model_validate(yaml.safe_load(raw) or {})
    return compile_local(spec, raw, now)


def admit_local(config: LocalBundleConfig, holder: BundleHolder) -> None:
    bundle = load_local(config.path, datetime.now(tz=UTC))
    holder.admit(bundle, "serve_and_warn", source="local")


def reload_if_changed(config: LocalBundleConfig, holder: BundleHolder, last_mtime: float) -> float:
    """Admit the file again when it changes; return the mtime that is now served."""
    mtime = config.path.stat().st_mtime
    if mtime != last_mtime:
        admit_local(config, holder)
    return mtime


async def run_local_reload(config: LocalBundleConfig, holder: BundleHolder) -> None:
    """The local counterpart of the poller: same loop, the file instead of the control plane.

    A broken edit logs and keeps the last good bundle serving, like a failed poll."""
    served = config.path.stat().st_mtime if config.path.exists() else 0.0

    async def once() -> None:
        nonlocal served
        served = reload_if_changed(config, holder, served)

    await run_periodic(once, config.reload_interval_s, (OSError, ValidationError, ValueError, yaml.YAMLError), "local bundle reload")
