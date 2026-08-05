from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import uuid4

import yaml
from dotenv import set_key
from pydantic import BaseModel, Field

from contract import mint_inference_token, private_key_from_b64
from control_plane.compiler import compile_and_store
from control_plane.models import ApiKey, MgmtToken, Model, Org, Provider
from control_plane.routes.org import KeyIn, ModelIn, ProviderIn
from control_plane.tokens import mint_management_token

if TYPE_CHECKING:
    from control_plane.config import Settings

logger = logging.getLogger(__name__)


class BootstrapSpec(BaseModel):
    org: str
    providers: list[ProviderIn] = Field(default_factory=list)
    models: list[ModelIn] = Field(default_factory=list)
    keys: list[KeyIn] = Field(default_factory=lambda: [KeyIn()])


def _spec_file(settings: Settings) -> Path | None:
    path = Path(settings.bootstrap.file)
    return path if path.exists() else None


def _parse_spec(spec_path: Path) -> BootstrapSpec:
    return BootstrapSpec.model_validate(yaml.safe_load(spec_path.read_text(encoding="utf-8")))


def _write_env(env_path: Path, minted: dict[str, str]) -> None:
    env_path.touch(exist_ok=True)
    for name, value in minted.items():
        set_key(env_path, name, value)


async def auto_bootstrap(settings: Settings) -> bool:
    """Seed an empty control plane from the bootstrap spec on first start.

    Applies the spec, mints the org, data-plane, and caller tokens, writes them to the
    configured env file, and compiles bundle v1. A non-empty database or a missing spec
    file makes this a no-op, so restarts never re-apply or re-mint.
    """
    spec_path = _spec_file(settings)
    if spec_path is None:
        return False
    if await Org.first() is not None:
        return False
    spec = _parse_spec(spec_path)
    now = datetime.now(tz=UTC)
    private_key = private_key_from_b64(settings.auth.token_signing_key)

    await Org(id=spec.org, name=spec.org, created_at=now).save()
    for p in spec.providers:
        await Provider(
            id=p.provider_id,
            org_id=spec.org,
            kind=p.kind,
            base_url=p.base_url,
            credential_ref=p.credential_ref,
            cache_read_multiplier=p.cache_read_multiplier,
            cache_write_multiplier=p.cache_write_multiplier,
        ).save()
    for m in spec.models:
        await Model(
            id=m.model_id,
            org_id=spec.org,
            provider_id=m.provider_id,
            upstream_model=m.upstream_model or m.model_id,
            input_price_per_mtok=m.input_price_per_mtok,
            output_price_per_mtok=m.output_price_per_mtok,
            context_window=m.context_window,
            max_output_tokens=m.max_output_tokens,
            capabilities=m.capabilities,
        ).save()
    caller_tokens = []
    for k in spec.keys:
        key_id = f"k-{uuid4().hex[:8]}"
        await ApiKey(id=key_id, org_id=spec.org, allowed_models=k.allowed_models, disabled=False, created_at=now).save()
        caller_tokens.append(mint_inference_token(key_id, spec.org, private_key, now))
    tokens = {}
    for env_name in ("GW_ORG_TOKEN", "GW_DP_TOKEN"):
        token_id = f"mt-{uuid4().hex[:8]}"
        await MgmtToken(id=token_id, org_id=spec.org, created_at=now, revoked=False).save()
        tokens[env_name] = mint_management_token(spec.org, private_key, now, token_id)
    version = await compile_and_store(spec.org, uuid4(), now, settings.bundle.staleness_bound, settings.bundle.signing_key)

    env_path = Path(settings.bootstrap.env_file)
    minted = {**tokens, **({"AIRLLM_TOKEN": caller_tokens[0]} if caller_tokens else {})}
    _write_env(env_path, minted)
    logger.info(
        "bootstrapped org %s: %d providers, %d models, %d keys, bundle v%d; tokens written to %s",
        spec.org,
        len(spec.providers),
        len(spec.models),
        len(spec.keys),
        version,
        env_path,
    )
    return True
