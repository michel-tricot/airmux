from __future__ import annotations

from typing import TYPE_CHECKING, Literal, cast

from sqlalchemy import func
from sqlmodel import col, or_, select

from contract import BundleV1, Catalog, CredentialEntry, KeyEntry, ModelEntry, ProviderEntry, canonical_json, sign_bundle, uuid7
from control_plane.db import current_session
from control_plane.models import Bundle, InferenceKey, Model, Org, PlaygroundSession, Provider, ProviderCredential, RuntimeConfiguration
from control_plane.models.runtime_configuration import runtime_configuration_changes

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID

    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

SIGNING_KEY_ID = "k1"


class UnknownOrgError(LookupError):
    def __init__(self, org_id: UUID) -> None:
        super().__init__(str(org_id))


async def publish_changes(now: datetime, signing_key: Ed25519PrivateKey) -> tuple[Bundle, ...]:
    await RuntimeConfiguration.advance(runtime_configuration_changes(current_session().sync_session))
    return await publish_pending(now, signing_key)


async def publish_pending(now: datetime, signing_key: Ed25519PrivateKey) -> tuple[Bundle, ...]:
    published: tuple[Bundle, ...] = ()
    configuration = await RuntimeConfiguration.next_pending()
    while configuration is not None:
        published = (*published, await _publish_revision(configuration, uuid7(), now, signing_key))
        configuration = await RuntimeConfiguration.next_pending()
    return published


async def _publish_revision(
    configuration: RuntimeConfiguration,
    bundle_id: UUID,
    now: datetime,
    signing_key: Ed25519PrivateKey,
) -> Bundle:
    org_id = configuration.org_id
    bundle = await compile_bundle(org_id, bundle_id, now)
    signed = sign_bundle(bundle, signing_key, SIGNING_KEY_ID)
    version = (await current_session().execute(select(func.max(Bundle.version)).where(Bundle.org_id == org_id))).scalar() or 0
    stored = await Bundle(
        id=bundle_id,
        org_id=org_id,
        version=version + 1,
        issued_at=now,
        configuration_revision=configuration.desired_revision,
        payload=canonical_json(bundle),
        signature=signed.signature,
        signing_key_id=signed.signing_key_id,
    ).save()
    configuration.published_revision = configuration.desired_revision
    await configuration.save()
    return stored


async def compile_bundle(org_id: UUID, bundle_id: UUID, now: datetime) -> BundleV1:
    """Compile the current transaction's visible state with caller-supplied identity and time."""
    org = await Org.find_by_id(org_id)
    if org is None:
        raise UnknownOrgError(org_id)
    key_rows = await InferenceKey.find(InferenceKey.org_id == org_id, order_by=col(InferenceKey.id))
    playground_sessions = await PlaygroundSession.find(PlaygroundSession.org_id == org_id, order_by=col(PlaygroundSession.id))
    provider_rows = await Provider.find(order_by=col(Provider.name))
    model_rows = await Model.find(order_by=col(Model.name))
    provider_names = {p.id: p.name for p in provider_rows}
    credential_order = (col(ProviderCredential.priority), col(ProviderCredential.name))
    credential_rows = await ProviderCredential.find(
        or_(ProviderCredential.org_id == org_id, col(ProviderCredential.org_id).is_(None)), order_by=credential_order
    )
    return BundleV1(
        bundle_id=bundle_id,
        org_id=org_id,
        issued_at=now,
        keys=[
            *[
                KeyEntry(key_id=str(key.id), org_id=key.org_id, workspace_id=key.workspace_id, token_hash=key.token_hash)
                for key in key_rows
                if not key.revoked
            ],
            *[
                KeyEntry(
                    key_id=str(playground_session.id),
                    org_id=playground_session.org_id,
                    workspace_id=playground_session.workspace_id,
                    token_hash=playground_session.token_hash,
                    expires_at=playground_session.expires_at,
                )
                for playground_session in playground_sessions
                if playground_session.active(now)
            ],
        ],
        catalog=Catalog(
            providers=[
                ProviderEntry.model_validate(
                    {
                        "provider_id": r.name,
                        "kind": r.kind,
                        "base_url": r.base_url,
                        "param_aliases": r.param_aliases,
                        "accepted_params": r.accepted_params,
                        "params_closed": r.params_closed,
                    }
                )
                for r in provider_rows
            ],
            credentials=[CredentialEntry(ref=r.secret_ref(), priority=r.priority, version=r.version) for r in credential_rows if r.enabled],
            models=[
                ModelEntry(
                    model_id=r.name,
                    provider_id=provider_names[r.provider_id],
                    upstream_model=r.upstream_model,
                    egress_kind=cast("Literal['openai_compatible', 'openai_responses', 'anthropic'] | None", r.egress_kind),
                    input_price_per_mtok=r.input_price_per_mtok,
                    output_price_per_mtok=r.output_price_per_mtok,
                    cache_read_price_per_mtok=r.cache_read_price_per_mtok,
                    cache_write_price_per_mtok=r.cache_write_price_per_mtok,
                    context_window=r.context_window,
                    max_output_tokens=r.max_output_tokens,
                    capabilities=r.capabilities,
                )
                for r in model_rows
            ],
        ),
    )
