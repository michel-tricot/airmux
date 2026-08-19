from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping

from probe_runtime import Support

CAPABILITY_PROBE_VERSION = 2
PARAMETER_PROBE_VERSION = 1
REACHABILITY_PROBE_VERSION = 1
REACHABILITY_DEFINITIVE = frozenset({"ok", "not_found", "bad_request", "access", "auth"})


def target_fingerprint(provider: Mapping[str, object], model: Mapping[str, object], endpoint: str, suite: str, version: int) -> str:
    provider_id = provider.get("id")
    base_url = provider.get("base_url")
    upstream_id = model.get("upstream_id") or model.get("id")
    payload = json.dumps(
        {
            "suite": suite,
            "version": version,
            "provider": provider_id,
            "base_url": base_url,
            "endpoint": endpoint,
            "upstream_id": upstream_id,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode()).hexdigest()[:20]


def current_targets(
    provider: Mapping[str, object], model: Mapping[str, object], endpoints: tuple[str, ...], suite: str, version: int
) -> dict[str, str]:
    return {endpoint: target_fingerprint(provider, model, endpoint, suite, version) for endpoint in endpoints}


def live_evidence_is_current(live_probe: Mapping[str, object], targets: Mapping[str, str], version: int) -> bool:
    return live_probe.get("version") == version and live_probe.get("targets") == targets


def merge_live_evidence(
    previous: Mapping[str, object],
    attempts: Mapping[str, list[str]],
    support: Mapping[str, Mapping[str, Support]],
    targets: Mapping[str, str],
    version: int,
    replace: bool,
) -> dict[str, object]:
    compatible = not replace and live_evidence_is_current(previous, targets, version)
    previous_attempts = previous.get("attempted") if compatible else {}
    previous_support = previous.get("support") if compatible else {}
    old_attempts = previous_attempts if isinstance(previous_attempts, Mapping) else {}
    old_support = previous_support if isinstance(previous_support, Mapping) else {}
    attempt_endpoints = {str(endpoint) for endpoint in old_attempts} | set(attempts)
    merged_attempts = {
        endpoint: sorted(set(_string_list(old_attempts.get(endpoint))) | set(attempts.get(endpoint, []))) for endpoint in attempt_endpoints
    }
    support_endpoints = {str(endpoint) for endpoint in old_support} | set(support)
    merged_support = {endpoint: {**_string_mapping(old_support.get(endpoint)), **dict(support.get(endpoint, {}))} for endpoint in support_endpoints}
    return {
        "version": version,
        "targets": dict(sorted(targets.items())),
        "attempted": dict(sorted(merged_attempts.items())),
        "support": dict(sorted(merged_support.items())),
    }


def _string_list(value: object) -> list[str]:
    return [item for item in value if isinstance(item, str)] if isinstance(value, list) else []


def _string_mapping(value: object) -> dict[str, str]:
    if not isinstance(value, Mapping):
        return {}
    return {str(key): item for key, item in value.items() if isinstance(item, str)}
