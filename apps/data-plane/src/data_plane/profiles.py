from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping

    from contract import BundleV1, ProviderEntry


@dataclass(frozen=True)
class CompiledProfile:
    """A provider's profile, precomputed for the request path: the alias map inverted so a
    colliding spelling is one lookup, the accepted params frozen for membership. Built once per
    bundle at admission, like every other snapshot index."""

    provider_id: str
    respelled: Mapping[str, str]  # provider spelling -> the canonical field it respells
    accepted: frozenset[str]
    params_closed: bool


def compile_profile(provider: ProviderEntry) -> CompiledProfile:
    return CompiledProfile(
        provider_id=provider.provider_id,
        respelled=MappingProxyType({spelling: canonical for canonical, spelling in provider.param_aliases.items()}),
        accepted=frozenset(provider.accepted_params or ()),
        params_closed=provider.params_closed,
    )


def index_profiles(bundle: BundleV1) -> dict[str, CompiledProfile]:
    return {provider.provider_id: compile_profile(provider) for provider in bundle.catalog.providers}
