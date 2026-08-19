from __future__ import annotations

from collections.abc import Iterable

CAPABILITIES = {
    "openai_compatible": frozenset({"streaming", "tools", "parallel_tools", "json_object", "json_schema", "reasoning"}),
    "openai_responses": frozenset({"streaming", "tools", "parallel_tools", "json_object", "json_schema", "reasoning"}),
    "anthropic": frozenset({"streaming", "tools", "parallel_tools", "reasoning"}),
}
INPUT_MODALITIES = {
    "openai_compatible": frozenset({"text", "image"}),
    "openai_responses": frozenset({"text", "image"}),
    "anthropic": frozenset({"text", "image"}),
}
OUTPUT_MODALITIES = {
    "openai_compatible": frozenset({"text"}),
    "openai_responses": frozenset({"text"}),
    "anthropic": frozenset({"text"}),
}


def supported_capabilities(egress_kind: str, capabilities: Iterable[str]) -> list[str]:
    available = CAPABILITIES.get(egress_kind, frozenset())
    return [capability for capability in capabilities if capability in available]


def supported_modalities(egress_kind: str, modalities: Iterable[str], *, output: bool = False) -> list[str]:
    available = (OUTPUT_MODALITIES if output else INPUT_MODALITIES).get(egress_kind, frozenset())
    return [modality for modality in modalities if modality in available]
