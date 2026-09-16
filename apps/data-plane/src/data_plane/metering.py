from __future__ import annotations

import functools
import json
import logging
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

import httpx
import tiktoken
from pydantic import BaseModel

from contract import DeniedUsageEventV1, RoutedUsageEventV1, UsdAmount, uuid7
from contract.money import USD_AMOUNT_QUANTUM, ZERO_USD
from data_plane.canonical import CanonicalTextPart, CanonicalUsage

if TYPE_CHECKING:
    from collections.abc import Sequence
    from uuid import UUID

    from contract import KeyEntry, ModelEntry, RoutedUsageStatus
    from data_plane.canonical import CanonicalRequest, CanonicalResponse
    from data_plane.egress.base import Ctx
    from data_plane.outbox import EventOutbox


logger = logging.getLogger("data_plane")

REJECTS_CREDENTIAL = frozenset({httpx.codes.UNAUTHORIZED, httpx.codes.FORBIDDEN})


@dataclass(frozen=True)
class RequestStart:
    request_id: UUID
    started_at: float


def cost_breakdown(usage: CanonicalUsage, model: ModelEntry) -> tuple[UsdAmount, UsdAmount]:
    fresh_input_tokens = max(0, usage.input_tokens - usage.cache_read_tokens - usage.cache_write_tokens)
    input_cost = (
        fresh_input_tokens * model.input_price_per_mtok
        + usage.cache_read_tokens * model.cache_read_price_per_mtok
        + usage.cache_write_tokens * model.cache_write_price_per_mtok
    ) / Decimal(1_000_000)
    output_cost = usage.output_tokens * model.output_price_per_mtok / Decimal(1_000_000)
    return input_cost.quantize(USD_AMOUNT_QUANTUM), output_cost.quantize(USD_AMOUNT_QUANTUM)


@functools.lru_cache(maxsize=64)
def _encoding(upstream_model: str) -> tiktoken.Encoding:
    try:
        return tiktoken.encoding_for_model(upstream_model)
    except KeyError:
        return tiktoken.get_encoding("o200k_base")


def estimate_tokens(text: str, model: ModelEntry) -> int:
    """Provider counts win where given; this fills the gap, notably partial accounting after a cancel."""
    if not text:
        return 0
    return len(_encoding(model.upstream_model).encode(text))


def status_for_error(error: Exception) -> RoutedUsageStatus:
    return "timeout" if isinstance(error, httpx.TimeoutException) else "upstream_error"


def status_for_upstream(status_code: int) -> RoutedUsageStatus:
    if status_code in REJECTS_CREDENTIAL:
        return "credential_rejected"
    return "rate_limited" if status_code == httpx.codes.TOO_MANY_REQUESTS else "upstream_error"


def _text_of(parts: Sequence[object]) -> str:
    rendered = []
    for part in parts:
        if isinstance(part, CanonicalTextPart):
            rendered.append(part.text)
        elif isinstance(part, BaseModel):
            payload = part.model_dump(mode="json", exclude_none=True, exclude={"data"})
            rendered.append(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
    return "\n".join(rendered)


def _prompt_text(request: CanonicalRequest) -> str:
    messages = "\n".join(f"{message.role}: {_text_of(message.content)}" for message in request.messages)
    tools = "\n".join(tool.model_dump_json(exclude_none=True) for tool in request.tools or ())
    response_format = request.response_format.model_dump_json(exclude_none=True) if request.response_format is not None else ""
    reasoning = request.reasoning.model_dump_json(exclude_none=True) if request.reasoning is not None else ""
    return "\n".join(value for value in (messages, tools, response_format, reasoning) if value)


def record_denied(
    outbox: EventOutbox,
    key: KeyEntry,
    bundle_id: UUID,
    request: CanonicalRequest,
    start: RequestStart,
) -> None:
    outbox.record(
        DeniedUsageEventV1(
            event_id=uuid7(),
            request_id=start.request_id,
            occurred_at=datetime.now(tz=UTC),
            org_id=key.org_id,
            workspace_id=key.workspace_id,
            key_id=key.key_id,
            model_id=request.model,
            provider_id="",
            bundle_id=bundle_id,
            input_tokens=0,
            output_tokens=0,
            cost_usd=ZERO_USD,
            max_output_tokens=None,
            latency_ms=int((time.monotonic() - start.started_at) * 1000),
            status="denied",
            stream=request.stream,
        )
    )


def record_usage(
    outbox: EventOutbox,
    ctx: Ctx,
    response: CanonicalResponse,
    status: RoutedUsageStatus,
    request: CanonicalRequest,
) -> None:
    usage = response.usage
    if usage.estimated:
        usage = CanonicalUsage(
            input_tokens=usage.input_tokens or estimate_tokens(_prompt_text(request), ctx.model),
            output_tokens=usage.output_tokens or estimate_tokens(_text_of(response.content), ctx.model),
            cache_read_tokens=usage.cache_read_tokens,
            cache_write_tokens=usage.cache_write_tokens,
            estimated=True,
        )
    cost_in, cost_out = cost_breakdown(usage, ctx.model)
    latency_ms = int((time.monotonic() - ctx.started_at) * 1000)
    outbox.record(
        RoutedUsageEventV1(
            event_id=uuid7(),
            request_id=ctx.request_id,
            occurred_at=datetime.now(tz=UTC),
            org_id=ctx.org_id,
            workspace_id=ctx.workspace_id,
            key_id=ctx.key_id,
            model_id=ctx.model.model_id,
            provider_id=ctx.provider.provider_id,
            bundle_id=ctx.bundle_id,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            max_output_tokens=request.max_output_tokens,
            cache_read_tokens=usage.cache_read_tokens,
            cache_write_tokens=usage.cache_write_tokens,
            cost_usd=cost_in + cost_out,
            cost_input_usd=cost_in,
            cost_output_usd=cost_out,
            latency_ms=latency_ms,
            status=status,
            stream=ctx.stream,
            credential_id=ctx.credential_id,
            credential_scope=ctx.credential_scope,
        ),
    )
    logger.info(
        "usage request_id=%s model=%s provider=%s status=%s stream=%s input_tokens=%d output_tokens=%d max_output_tokens=%s "
        "cache_read=%d cache_write=%d estimated=%s cost_usd=%s latency_ms=%d",
        ctx.request_id,
        ctx.model.model_id,
        ctx.provider.provider_id,
        status,
        ctx.stream,
        usage.input_tokens,
        usage.output_tokens,
        request.max_output_tokens,
        usage.cache_read_tokens,
        usage.cache_write_tokens,
        usage.estimated,
        cost_in + cost_out,
        latency_ms,
    )
