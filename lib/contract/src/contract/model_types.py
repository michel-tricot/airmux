from __future__ import annotations

from typing import Literal, cast, get_args

ParameterSupport = Literal["supported", "unsupported"]
Modality = Literal["text", "image", "audio", "video", "pdf"]
MODALITIES = cast("tuple[Modality, ...]", get_args(Modality))
Capability = Literal["streaming", "tools", "reasoning", "structured_output"]
