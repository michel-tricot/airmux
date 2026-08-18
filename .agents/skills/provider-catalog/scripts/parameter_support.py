from __future__ import annotations

import json
from collections.abc import Mapping

SUPPORT = frozenset({"supported", "unsupported"})
ENDPOINTS = frozenset({"chat/completions", "responses", "messages"})


def resolve_parameter_support(evidence: Mapping, endpoint: str) -> dict[str, str]:
    resolved = dict(((evidence.get("vendor_docs") or {}).get("support") or {}).get(endpoint) or {})
    resolved.update(((evidence.get("live_probe") or {}).get("support") or {}).get(endpoint) or {})
    return {parameter: status for parameter, status in sorted(resolved.items()) if status in SUPPORT}


def classify_parameter_response(status: int, body: str, parameter: str) -> str | None:
    if 200 <= status < 300:
        return "supported"
    if status != 400:
        return None
    try:
        payload = json.loads(body)
        message = str((payload.get("error") or {}).get("message") or payload)
    except (json.JSONDecodeError, AttributeError):
        message = body
    lowered = message.casefold()
    spellings = (parameter, parameter.replace("_", " "), parameter.replace("_", "."))
    named = any(spelling.casefold() in lowered for spelling in spellings)
    rejected = "unsupported parameter" in lowered or "not supported" in lowered or "does not support" in lowered
    return "unsupported" if named and rejected else None
