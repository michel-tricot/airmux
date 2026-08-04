from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ConfigDict

if TYPE_CHECKING:
    from uuid import UUID

    from contract import ModelEntry, ProviderEntry


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
    org_id: str = ""
    key_id: str = ""
    bundle_id: UUID | None = None
    started_at: float = field(default_factory=time.monotonic)


@dataclass
class StreamState:
    buffer: bytes = b""


class UpstreamStreamError(Exception):
    """A provider error delivered as a stream event after a 200, outside the HTTP status path."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)
