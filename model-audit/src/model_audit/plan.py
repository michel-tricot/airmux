from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from model_audit.models import Case, ClientMode, Experiment, Plan, Target, Transport

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence


@dataclass(frozen=True)
class Filters:
    provider: str | None = None
    model: str | None = None
    case: str | None = None
    client_mode: ClientMode = "api"
    surface: str | None = None
    transport: Transport | None = None


DEFAULT_FILTERS = Filters()


def _selected(target: Target, case: Case, filters: Filters) -> bool:
    return not any(
        (
            filters.provider is not None and target.provider_id != filters.provider,
            filters.model is not None and target.model_id != filters.model,
            filters.case is not None and case.id != filters.case,
            filters.surface is not None and target.surface_id != filters.surface,
            not case.applies_to.accepts(target.endpoint, target.egress_kind, filters.client_mode),
        )
    )


def build_plan(
    targets: Sequence[Target],
    cases: Sequence[Case],
    driver_endpoints: Mapping[str, frozenset[str]],
    filters: Filters = DEFAULT_FILTERS,
) -> Plan:
    client = "http" if filters.client_mode == "api" else None
    experiments: list[Experiment] = []
    unavailable = 0
    for target in sorted(targets, key=lambda item: (item.provider_id, item.model_id, item.surface_id)):
        for case in sorted(cases, key=lambda item: item.id):
            if not _selected(target, case, filters):
                continue
            driver_id = client or ("anthropic" if target.egress_kind == "anthropic" else "openai")
            if target.endpoint not in driver_endpoints.get(driver_id, frozenset()):
                unavailable += len(case.transports)
                continue
            experiments.extend(
                Experiment(target=target, case=case, driver_id=driver_id, transport=transport)
                for transport in case.transports
                if filters.transport is None or filters.transport == transport
            )
    return Plan(experiments=tuple(experiments), unavailable=unavailable)
