from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable

    from contract import ModelEntry, ProviderEntry
    from data_plane.canonical import CanonicalRequest

# A named pipeline of provider/model reconciliations, applied once per request before the adapter runs.
# Each rule reads capability data off the catalog (never a provider name) so a new provider is a bundle
# row, not a branch. Add finicky cross-provider details (param clamps, feature gating) here as new rules.

Rule = "Callable[[CanonicalRequest, ModelEntry, ProviderEntry], CanonicalRequest]"


def clamp_max_tokens(req: CanonicalRequest, model: ModelEntry, provider: ProviderEntry) -> CanonicalRequest:  # noqa: ARG001 uniform rule signature
    """A client aimed at one provider cannot know another's completion cap; clamp to the target model's."""
    if req.max_tokens and model.max_output_tokens and req.max_tokens > model.max_output_tokens:
        return req.model_copy(update={"max_tokens": model.max_output_tokens})
    return req


RULES: list[Callable[[CanonicalRequest, ModelEntry, ProviderEntry], CanonicalRequest]] = [clamp_max_tokens]


def normalize_request(req: CanonicalRequest, model: ModelEntry, provider: ProviderEntry) -> CanonicalRequest:
    for rule in RULES:
        req = rule(req, model, provider)
    return req
