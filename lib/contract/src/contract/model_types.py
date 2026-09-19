from __future__ import annotations

from typing import Annotated, Literal, cast, get_args

from pydantic import Field

ParameterSupport = Literal["supported", "unsupported"]
Modality = Literal["text", "image", "audio", "video", "pdf"]
MODALITIES = cast("tuple[Modality, ...]", get_args(Modality))
Capability = Literal["streaming", "tools", "reasoning", "structured_output"]

ProviderName = Annotated[str, Field(min_length=1, max_length=63, pattern=r"^[a-z0-9][a-z0-9_-]*$")]
AdapterKind = Annotated[str, Field(min_length=1, max_length=63, pattern=r"^[a-z0-9][a-z0-9_]*$")]
ModelName = Annotated[str, Field(min_length=1, max_length=255)]
TokenLimit = Annotated[int, Field(ge=1, le=100_000_000)]
