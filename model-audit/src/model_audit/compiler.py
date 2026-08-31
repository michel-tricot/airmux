from __future__ import annotations

import json
from dataclasses import dataclass
from hashlib import sha256
from typing import TYPE_CHECKING, cast

from model_audit.cases import fingerprint
from model_audit.drivers.wire import gateway_options
from model_audit.models import Case, Request, RequestArtifact

if TYPE_CHECKING:
    from collections.abc import Mapping

    from pydantic import JsonValue

    from model_audit.models import Target, Transport
    from model_audit.surfaces.base import SurfaceCodec


class UnrepresentableRequestError(ValueError):
    pass


PAIRED_OUTPUT_FLOOR = 4096


@dataclass(frozen=True)
class CompiledPair:
    direct: RequestArtifact
    gateway: RequestArtifact


@dataclass(frozen=True)
class CompileOptions:
    aliases: Mapping[str, str] | None = None
    gateway: bool = False


DEFAULT_COMPILE_OPTIONS = CompileOptions()


def _digest(value: object) -> str:
    serialized = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return sha256(serialized.encode()).hexdigest()[:20]


def _redact(value: JsonValue, name: str | None = None) -> JsonValue:
    if isinstance(value, dict):
        return {key: _redact(item, key) for key, item in value.items()}
    if isinstance(value, list):
        return [_redact(item) for item in value]
    if name in {"data", "file_data", "image_url"} and isinstance(value, str) and ("base64," in value or name == "data"):
        return f"<content:{sha256(value.encode()).hexdigest()[:16]}>"
    return value


def _active_fields(request: Request) -> frozenset[str]:
    values = request.model_dump(mode="python", exclude_none=True)
    return frozenset(name for name, value in values.items() if value not in ((), [], {}))


def _validate(codec: SurfaceCodec, case: Case) -> None:
    if case.follow_up is not None and not codec.supports_continuation:
        message = f"{codec.id} cannot carry provider-issued continuation state"
        raise UnrepresentableRequestError(message)
    requests = (case.request,) + ((case.follow_up,) if case.follow_up is not None else ())
    missing = sorted({field for request in requests for field in _active_fields(request) if field not in codec.supported_fields})
    if missing:
        message = f"{codec.id} cannot represent request fields: {', '.join(missing)}"
        raise UnrepresentableRequestError(message)


def _semantic(case: Case) -> dict[str, JsonValue]:
    request = case.request.model_dump(mode="json", exclude_none=True)
    request["max_tokens"] = case.max_output_tokens
    follow_up_request = case.follow_up
    follow_up = None
    if follow_up_request is not None:
        follow_up = follow_up_request.model_dump(mode="json", exclude_none=True)
        follow_up["max_tokens"] = follow_up_request.max_tokens or case.execution.max_output_tokens
    return {
        "case": fingerprint(case),
        "request": cast("JsonValue", _redact(cast("JsonValue", request))),
        **({"follow_up": cast("JsonValue", _redact(cast("JsonValue", follow_up)))} if follow_up is not None else {}),
    }


def compile_request(
    codec: SurfaceCodec,
    model: str,
    case: Case,
    transport: Transport,
    options: CompileOptions = DEFAULT_COMPILE_OPTIONS,
) -> RequestArtifact:
    _validate(codec, case)
    body = {**codec.encode(model, case, transport), **(gateway_options(codec.endpoint, case) if options.gateway else {})}
    if options.aliases:
        body = {options.aliases.get(name, name): value for name, value in body.items()}
    semantic = _semantic(case)
    redacted = cast("dict[str, JsonValue]", _redact(cast("JsonValue", body)))
    return RequestArtifact(
        surface_id=codec.id,
        endpoint=codec.endpoint,
        body_fingerprint=_digest(redacted),
        semantic_fingerprint=_digest(semantic),
        redacted_body=redacted,
    )


def compile_pair(
    target: Target,
    direct_codec: SurfaceCodec,
    gateway_codec: SurfaceCodec,
    case: Case,
    transport: Transport,
) -> CompiledPair:
    direct = compile_request(direct_codec, target.upstream_model, case, transport, CompileOptions(aliases=target.param_aliases))
    gateway = compile_request(gateway_codec, target.model_id, case, transport, CompileOptions(gateway=True))
    if direct.semantic_fingerprint != gateway.semantic_fingerprint:
        message = f"{direct_codec.id} and {gateway_codec.id} compiled different semantic requests"
        raise UnrepresentableRequestError(message)
    return CompiledPair(direct=direct, gateway=gateway)


def execution_case(target: Target, case: Case) -> Case:
    tests_output_limit = any(claim.dimension == "option" and claim.name == "max_tokens" for claim in case.claims)
    if tests_output_limit:
        return case
    requested = max(case.max_output_tokens, PAIRED_OUTPUT_FLOOR)
    maximum = min(requested, target.max_output_tokens) if target.max_output_tokens is not None else requested
    request = case.request.model_copy(update={"max_tokens": maximum})
    follow_up = case.follow_up.model_copy(update={"max_tokens": maximum}) if case.follow_up is not None else None
    return case.model_copy(update={"request": request, "follow_up": follow_up})
