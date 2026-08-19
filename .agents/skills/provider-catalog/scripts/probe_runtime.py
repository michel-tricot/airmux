from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal

from catalog_io import atomic_write_text

Support = Literal["supported", "unsupported"]
OutcomeReason = Literal[
    "observed",
    "explicit_rejection",
    "behavior_not_observed",
    "authentication",
    "access",
    "rate_limit",
    "timeout",
    "server_error",
    "transport_error",
    "unclassified_error",
]


@dataclass(frozen=True)
class ProbeOutcome:
    support: Support | None
    reason: OutcomeReason
    detail: str = ""


@dataclass(frozen=True)
class ProbeReportEntry:
    provider: str
    model: str
    endpoint: str
    probe: str
    support: Support | None
    reason: OutcomeReason
    detail: str = ""


def http_outcome(status: int, support: Support | None, detail: str) -> ProbeOutcome:
    if support == "supported":
        return ProbeOutcome(support, "observed")
    if support == "unsupported":
        return ProbeOutcome(support, "explicit_rejection", detail)
    if 200 <= status < 300:
        return ProbeOutcome(None, "behavior_not_observed")
    if status == 401:
        return ProbeOutcome(None, "authentication", detail)
    if status == 403:
        return ProbeOutcome(None, "access", detail)
    if status == 429:
        return ProbeOutcome(None, "rate_limit", detail)
    if status >= 500:
        return ProbeOutcome(None, "server_error", detail)
    return ProbeOutcome(None, "unclassified_error", detail)


def write_probe_report(path: Path, entries: list[ProbeReportEntry]) -> None:
    payload = [asdict(entry) for entry in sorted(entries, key=lambda item: (item.provider, item.model, item.endpoint, item.probe))]
    atomic_write_text(path, json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
