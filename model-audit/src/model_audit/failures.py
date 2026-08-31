from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from model_audit.models import FailureKind, Observation

UNSUPPORTED_PATTERNS = (
    "not supported",
    "unsupported",
    "does not support",
    "is not available",
    "not enabled for",
    "cannot be used with",
    "may not be enabled when",
    "is incompatible with",
    "extra inputs are not permitted",
    "extra_forbidden",
)
ACCESS_CODES = {"direct_authentication", "direct_model_access", "gateway_authentication", "not_run", "provider_billing_access"}
HARNESS_CODES = {"client_exception", "harness_request_error", "sdk_protocol_error"}
ERROR_TOPICS = {
    "image": ("image", "vision"),
    "pdf": ("pdf", "document"),
    "reasoning": ("reasoning", "thinking", "effort"),
    "structured_output": ("json", "schema", "response_format"),
    "tools": ("tool", "function"),
    "temperature": ("temperature",),
    "top_p": ("top_p", "top p"),
    "stop": ("stop",),
    "seed": ("seed",),
    "tokens": ("max_tokens", "max tokens", "token limit"),
    "model": ("model",),
}


@dataclass(frozen=True)
class ClassifiedFailure:
    kind: FailureKind
    category: str
    subject: str | None
    retryable: bool


def _message(observation: Observation) -> str:
    return " ".join((observation.error_message or "").casefold().split())


def explicit_unsupported(observation: Observation) -> bool:
    failure = observation.failure
    return bool(failure is not None and failure.kind == "unsupported") or (
        observation.outcome == "rejected" and any(pattern in _message(observation) for pattern in UNSUPPORTED_PATTERNS)
    )


def classify(observation: Observation) -> ClassifiedFailure | None:
    if observation.outcome == "success":
        return None
    failure = observation.failure
    code = (observation.error_code or "").casefold()
    message = _message(observation)
    subject = failure.subject if failure is not None else None
    if subject is None:
        subject = next((name for name, terms in ERROR_TOPICS.items() if any(term in message for term in terms)), None)
    if observation.error_code in ACCESS_CODES:
        kind: FailureKind = "access"
        category = str(observation.error_code)
    elif observation.error_code in HARNESS_CODES:
        kind = "protocol"
        category = "client_protocol"
    elif explicit_unsupported(observation):
        kind = "unsupported"
        category = "unsupported"
    elif "rate" in code or "rate limit" in message:
        kind = "transient"
        category = "rate_limit"
    elif observation.http_status is not None:
        kind = failure.kind if failure is not None else "unknown"
        suffix = f":{subject}" if subject is not None else ""
        category = f"http_{observation.http_status // 100}xx{suffix}"
    elif code:
        kind = failure.kind if failure is not None else "unknown"
        category = re.sub(r"[^a-z0-9]+", "_", code).strip("_")
    else:
        kind = failure.kind if failure is not None else "unknown"
        category = observation.outcome
    return ClassifiedFailure(
        kind=kind,
        category=category,
        subject=subject,
        retryable=observation.retryable,
    )
