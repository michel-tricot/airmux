from __future__ import annotations

from typing import TYPE_CHECKING

from sqlmodel import col, or_

from contract import BundleV1, Catalog, CredentialEntry, KeyEntry, ModelEntry, ProviderEntry, uuid7
from control_plane.models import (
    Bundle,
    BundleState,
    InferenceKey,
    Model,
    Org,
    PlaygroundSession,
    Provider,
    ProviderCredential,
)
from control_plane.models.policy import Policy

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID

    from control_plane.models.bundle_state import BundleGenerations


class UnknownOrgError(LookupError):
    def __init__(self, org_id: UUID) -> None:
        super().__init__(str(org_id))


class PublicationError(RuntimeError):
    def __init__(self, org_id: UUID, generations: BundleGenerations) -> None:
        self.org_id = org_id
        self.generations = generations
        super().__init__(f"bundle publication failed for organization {org_id}")


async def publish_next(now: datetime) -> Bundle | None:
    org_id = await BundleState.next_pending(now)
    if org_id is None:
        return None
    if not await BundleState.try_lock(org_id):
        return None
    state, generations = await BundleState.target(org_id)
    if state.is_current(generations):
        return None
    bundle_id = uuid7()
    try:
        bundle = await compile_bundle(org_id, bundle_id, now)
    except Exception as error:
        raise PublicationError(org_id, generations) from error
    stored = await Bundle(
        id=bundle_id,
        org_id=org_id,
        global_generation=generations.global_,
        org_generation=generations.org,
        payload=bundle.model_dump_json(),
    ).save()
    await state.mark_published(bundle_id, generations)
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
    policies = await Policy.find(Policy.org_id == org_id, col(Policy.enabled).is_(True), order_by=col(Policy.id))
    return BundleV1(
        bundle_id=bundle_id,
        org_id=org_id,
        issued_at=now,
        policies=tuple(policy.entry() for policy in policies),
        keys=[
            *[
                KeyEntry(key_id=str(key.id), org_id=key.org_id, workspace_id=key.workspace_id, user_id=key.user_id, token_hash=key.token_hash)
                for key in key_rows
                if not key.revoked
            ],
            *[
                KeyEntry(
                    key_id=str(playground_session.id),
                    org_id=playground_session.org_id,
                    workspace_id=playground_session.workspace_id,
                    user_id=playground_session.user_id,
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
                    egress_kind=r.egress_kind,
                    input_price_per_mtok=r.input_price_per_mtok,
                    output_price_per_mtok=r.output_price_per_mtok,
                    cache_read_price_per_mtok=r.cache_read_price_per_mtok,
                    cache_write_price_per_mtok=r.cache_write_price_per_mtok,
                    context_window=r.context_window,
                    max_output_tokens=r.max_output_tokens,
                    input_modalities=r.input_modalities,
                    output_modalities=r.output_modalities,
                    capabilities=r.capabilities,
                    parameter_support=r.parameter_support,
                )
                for r in model_rows
            ],
        ),
    )
