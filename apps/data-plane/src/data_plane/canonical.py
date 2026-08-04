from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ConfigDict

if TYPE_CHECKING:
    from gw_contract import ModelEntry, ProviderEntry


class CanonicalRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    model: str
    messages: list[dict[str, Any]]
    stream: bool = False
    max_tokens: int | None = None
    temperature: float | None = None
    tools: list[dict[str, Any]] | None = None


class Usage(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0
    estimated: bool = False


class CanonicalResponse(BaseModel):
    id: str
    model: str
    content: list[dict[str, Any]]
    finish_reason: str | None
    usage: Usage


class CanonicalChunk(BaseModel):
    id: str
    delta: dict[str, Any]
    finish_reason: str | None = None


class CanonicalError(BaseModel):
    status: int
    code: str
    message: str


@dataclass(frozen=True)
class RawEvent:
    data: bytes
    name: str | None = None


@dataclass(frozen=True)
class UpstreamRequest:
    method: str
    url: str
    headers: dict[str, str]
    body: bytes


@dataclass(frozen=True)
class Ctx:
    request_id: str
    model: ModelEntry
    provider: ProviderEntry
    stream: bool = False


@dataclass
class StreamState:
    buffer: bytes = b""
    extra: dict[str, Any] = field(default_factory=dict)
