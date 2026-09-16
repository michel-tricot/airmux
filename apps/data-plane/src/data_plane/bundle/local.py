"""A bundle written by hand, for a data plane with no control plane.

The spec compiles to the same BundleV1 the poller fetches, and enters through the same
admit(). The request path never learns the source. The file is
trusted because the operator owns the filesystem it sits on."""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Annotated
from uuid import UUID, uuid5

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from contract import BundleV1, Catalog, CredentialEntry, KeyEntry, ModelEntry, ProviderEntry, SecretPurpose, SecretRef, token_hash
from contract.policies import PolicyEntry
from contract.refs import resolve_refs
from contract.taxonomy import TaxonomyLoader, TaxonomySpec, parse_taxonomy
from data_plane.bundle.base import BundleSource
from data_plane.bundle.holder import BundleSet
from data_plane.tasks import run_periodic

if TYPE_CHECKING:
    from data_plane.bundle.config import LocalBundleConfig
    from data_plane.bundle.holder import BundleHolder

logger = logging.getLogger("data_plane")

LOCAL_ORG = UUID(int=0)
LOCAL_WORKSPACE = UUID(int=0)
# Fixed namespace for uuid5, so ids are stable across reloads. A stable secret_id keeps the
# credential resolver cache warm; a content-derived bundle_id changes only when the file does.
_NAMESPACE = UUID("6c1a8f7e-4b62-4b8e-9f0d-2a52e07f1a11")


class LocalKey(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", hide_input_in_errors=True)

    token: Annotated[str, Field(pattern=r"^sk-inf-\S+$", max_length=512)]
    user_id: UUID


class LocalBundleSpec(BaseModel):
    """Local inference keys and policies with an inline or file-backed taxonomy."""

    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    keys: list[LocalKey] = Field(min_length=1)
    taxonomy: Path | TaxonomySpec
    policies: tuple[PolicyEntry, ...] = ()

    @field_validator("keys")
    @classmethod
    def unique_keys(cls, keys: list[LocalKey]) -> list[LocalKey]:
        if len(keys) != len({key.token for key in keys}):
            message = "inference keys must be unique"
            raise ValueError(message)
        return keys


def compile_local(spec: LocalBundleSpec, taxonomy: TaxonomySpec, raw: str, now: datetime) -> BundleV1:
    """Pure, like the control plane's compiler: all nondeterminism comes in through the arguments."""
    if not taxonomy.providers or not taxonomy.models:
        message = "a local taxonomy must contain providers and models"
        raise ValueError(message)
    keys = [
        KeyEntry(key_id=f"local-{position}", org_id=LOCAL_ORG, workspace_id=LOCAL_WORKSPACE, user_id=key.user_id, token_hash=token_hash(key.token))
        for position, key in enumerate(spec.keys)
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
        for provider in taxonomy.providers
    ]
    return BundleV1(
        bundle_id=uuid5(_NAMESPACE, raw),
        org_id=LOCAL_ORG,
        issued_at=now,
        keys=keys,
        policies=spec.policies,
        catalog=Catalog(
            providers=[
                ProviderEntry(
                    provider_id=provider.provider_id,
                    kind=provider.kind,
                    base_url=provider.base_url,
                    param_aliases=provider.param_aliases,
                    accepted_params=provider.accepted_params,
                    params_closed=provider.params_closed,
                )
                for provider in taxonomy.providers
            ],
            models=[
                ModelEntry(
                    model_id=model.model_id,
                    provider_id=model.provider_id,
                    upstream_model=model.upstream_model or model.model_id,
                    egress_kind=model.egress_kind,
                    input_price_per_mtok=model.input_price_per_mtok,
                    output_price_per_mtok=model.output_price_per_mtok,
                    cache_read_price_per_mtok=model.cache_read_price_per_mtok,
                    cache_write_price_per_mtok=model.cache_write_price_per_mtok,
                    context_window=model.context_window,
                    max_output_tokens=model.max_output_tokens,
                    input_modalities=model.input_modalities,
                    output_modalities=model.output_modalities,
                    capabilities=model.capabilities,
                    parameter_support=model.parameter_support,
                )
                for model in taxonomy.models
            ],
            credentials=credentials,
        ),
    )


def load_local(path: Path, now: datetime) -> BundleV1:
    raw = path.read_text(encoding="utf-8")
    document = yaml.load(raw, Loader=TaxonomyLoader) or {}  # noqa: S506 TaxonomyLoader subclasses SafeLoader
    spec = LocalBundleSpec.model_validate(resolve_refs(document, base_dir=path.parent))
    taxonomy = parse_taxonomy(path.parent / spec.taxonomy) if isinstance(spec.taxonomy, Path) else spec.taxonomy
    identity = spec.model_dump_json() + "\n" + taxonomy.model_dump_json()
    return compile_local(spec, taxonomy, identity, now)


class LocalBundleSource(BundleSource):
    """Loads a local bundle at boot and admits later file changes."""

    def __init__(self, config: LocalBundleConfig, holder: BundleHolder) -> None:
        self._config = config
        self._holder = holder
        self._served_bundle: UUID | None = None

    def load(self) -> None:
        bundle = load_local(self._config.path, datetime.now(tz=UTC))
        if bundle.bundle_id == self._served_bundle:
            return
        self._holder.swap(BundleSet.from_bundles((bundle,)), source="local")
        self._served_bundle = bundle.bundle_id

    async def once(self) -> None:
        await asyncio.to_thread(self.load)

    async def run(self) -> None:
        await run_periodic(
            self.once,
            self._config.reload_interval_s,
            (OSError, ValidationError, ValueError, yaml.YAMLError),
            "local bundle reload",
        )

    def start(self, task_group: asyncio.TaskGroup, /) -> tuple[asyncio.Task[None], ...]:
        try:
            self.load()
        except (OSError, ValidationError, ValueError, yaml.YAMLError):
            logger.exception("local bundle %s did not load, serving 503 until it does", self._config.path)
        return (task_group.create_task(self.run(), name="local bundle reload"),)
