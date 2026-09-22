from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from contract import Capability, Modality
    from contract.model_types import RequestCapability
    from data_plane.canonical import CanonicalRequest

_PART_CAPABILITIES: dict[str, RequestCapability] = {"reasoning": "reasoning", "tool_call": "tools", "tool_result": "tools"}
_STREAMING: frozenset[Capability] = frozenset({"streaming"})
_PART_MODALITIES: dict[str, Modality] = {"image": "image", "document": "pdf"}


@dataclass(frozen=True, slots=True)
class RequestRequirements:
    capabilities: frozenset[Capability]
    input_modalities: frozenset[Modality]
    requested_capabilities: frozenset[RequestCapability]

    @classmethod
    def of(cls, request: CanonicalRequest) -> RequestRequirements:
        capabilities: set[RequestCapability] = set()
        modalities: set[Modality] = set()
        for message in request.messages:
            for part in message.content:
                if capability := _PART_CAPABILITIES.get(part.type):
                    capabilities.add(capability)
                if modality := _PART_MODALITIES.get(part.type):
                    modalities.add(modality)
        if request.tools or request.tool_choice is not None:
            capabilities.add("tools")
        if request.reasoning is not None:
            capabilities.add("reasoning")
        if request.response_format is not None and request.response_format.type != "text":
            capabilities.add("structured_output")
        requested = frozenset(capabilities)
        return cls(requested | _STREAMING if request.stream else requested, frozenset(modalities), requested)
