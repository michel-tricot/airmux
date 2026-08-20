from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from provider_parity.models import Case, Experiment, Plan, Target, Transport

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence


@dataclass(frozen=True)
class Filters:
    provider: str | None = None
    model: str | None = None
    case: str | None = None
    sdk: str | None = None
    surface: str | None = None
    transport: Transport | None = None
    include_unknown: bool = False


def _selected(target: Target, case: Case, filters: Filters) -> bool:
    return not any(
        (
            filters.provider is not None and target.provider_id != filters.provider,
            filters.model is not None and target.model_id != filters.model,
            filters.case is not None and case.id != filters.case,
            filters.surface is not None and target.surface_id != filters.surface,
        )
    )


def _applicable(target: Target, case: Case, include_unknown: bool) -> bool:
    if not case.requires.capabilities <= target.capabilities:
        return False
    if not case.requires.input_modalities <= target.input_modalities:
        return False
    return include_unknown or all(target.parameter_support.get(parameter) == "supported" for parameter in case.requires.parameters)


def build_plan(targets: Sequence[Target], cases: Sequence[Case], drivers: Mapping[str, frozenset[str]], filters: Filters | None = None) -> Plan:
    filters = filters or Filters()
    experiments: list[Experiment] = []
    skipped = 0
    for target in targets:
        for case in cases:
            if not _selected(target, case, filters):
                continue
            if not _applicable(target, case, filters.include_unknown):
                skipped += 1
                continue
            compatible = [driver_id for driver_id, endpoints in sorted(drivers.items()) if target.endpoint in endpoints]
            if filters.sdk is not None:
                compatible = [driver_id for driver_id in compatible if driver_id == filters.sdk]
            if not compatible:
                skipped += 1
                continue
            for driver_id in compatible:
                for transport in case.transports:
                    if filters.transport is not None and transport != filters.transport:
                        continue
                    if transport == "streamed" and "streaming" not in target.capabilities:
                        continue
                    experiments.append(Experiment(target=target, case=case, driver_id=driver_id, transport=transport))
    return Plan(experiments=tuple(experiments), skipped=skipped)
