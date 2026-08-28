from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from model_audit.catalog import SURFACES
from model_audit.models import Case, ClientMode, Experiment, Plan, Target, Transport

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence


@dataclass(frozen=True)
class Filters:
    provider: str | None = None
    model: str | None = None
    cases: tuple[str, ...] = ()
    client_mode: ClientMode = "api"
    direct_surface: str | None = None
    gateway_surfaces: tuple[str, ...] = ()
    transport: Transport | None = None


DEFAULT_FILTERS = Filters()


def _case_selected(case_id: str, selectors: tuple[str, ...]) -> bool:
    return not selectors or any(case_id == selector or case_id.startswith(f"{selector}.") for selector in selectors)


def _selected(target: Target, case: Case, filters: Filters) -> bool:
    return not any(
        (
            filters.provider is not None and target.provider_id != filters.provider,
            filters.model is not None and target.model_id != filters.model,
            filters.direct_surface is None and target.egress_kind != target.gateway_egress_kind,
            not _case_selected(case.id, filters.cases),
            filters.direct_surface is not None and target.surface_id != filters.direct_surface,
            not case.applies_to.accepts(target.endpoint, target.egress_kind, filters.client_mode),
        )
    )


def _driver(kind: str, client_mode: ClientMode) -> str:
    if client_mode == "api":
        return "http"
    return "anthropic" if kind == "anthropic" else "openai"


def _gateway_surfaces(target: Target, filters: Filters) -> tuple[str, ...]:
    if not filters.gateway_surfaces:
        return (target.surface_id,)
    if "all" in filters.gateway_surfaces:
        return tuple(SURFACES)
    return tuple(dict.fromkeys(filters.gateway_surfaces))


def build_plan(
    targets: Sequence[Target],
    cases: Sequence[Case],
    driver_endpoints: Mapping[str, frozenset[str]],
    filters: Filters = DEFAULT_FILTERS,
) -> Plan:
    experiments: list[Experiment] = []
    unavailable = 0
    for target in sorted(targets, key=lambda item: (item.provider_id, item.model_id, item.surface_id)):
        for case in sorted(cases, key=lambda item: item.id):
            if not _selected(target, case, filters):
                continue
            for gateway_surface_id in _gateway_surfaces(target, filters):
                gateway_definition = SURFACES.get(gateway_surface_id)
                if gateway_definition is None:
                    unavailable += len(case.transports)
                    continue
                _, gateway_endpoint, gateway_kind = gateway_definition
                if not case.applies_to.accepts(gateway_endpoint, target.egress_kind, filters.client_mode):
                    continue
                direct_driver_id = _driver(target.egress_kind, filters.client_mode)
                gateway_driver_id = _driver(gateway_kind, filters.client_mode)
                if target.endpoint not in driver_endpoints.get(direct_driver_id, frozenset()) or gateway_endpoint not in driver_endpoints.get(
                    gateway_driver_id, frozenset()
                ):
                    unavailable += len(case.transports)
                    continue
                experiments.extend(
                    Experiment(
                        target=target,
                        case=case,
                        direct_driver_id=direct_driver_id,
                        gateway_driver_id=gateway_driver_id,
                        gateway_surface_id=gateway_surface_id,
                        gateway_endpoint=gateway_endpoint,
                        transport=transport,
                    )
                    for transport in case.transports
                    if filters.transport is None or filters.transport == transport
                )
    return Plan(experiments=tuple(experiments), unavailable=unavailable)
