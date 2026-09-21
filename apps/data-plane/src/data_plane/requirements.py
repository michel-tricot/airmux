from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from contract import Capability, Modality
    from contract.model_types import RequestCapability
    from data_plane.canonical import CanonicalRequest


def required_capabilities(request: CanonicalRequest) -> frozenset[Capability]:
    part_capabilities: dict[str, Capability] = {"reasoning": "reasoning", "tool_call": "tools", "tool_result": "tools"}
    capabilities = {capability for message in request.messages for part in message.content if (capability := part_capabilities.get(part.type))}
    if request.stream:
        capabilities.add("streaming")
    if request.tools or request.tool_choice is not None:
        capabilities.add("tools")
    if request.reasoning is not None:
        capabilities.add("reasoning")
    if request.response_format is not None and request.response_format.type != "text":
        capabilities.add("structured_output")
    return frozenset(capabilities)


def required_input_modalities(request: CanonicalRequest) -> frozenset[Modality]:
    part_modalities: dict[str, Modality] = {"image": "image", "document": "pdf"}
    return frozenset(modality for message in request.messages for part in message.content if (modality := part_modalities.get(part.type)))


def requested_capabilities(request: CanonicalRequest) -> frozenset[RequestCapability]:
    return frozenset(capability for capability in required_capabilities(request) if capability != "streaming")
