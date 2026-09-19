from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, cast

from data_plane.budgets import BudgetBackend, NoBudgetBackend

if TYPE_CHECKING:
    import httpx
    from starlette.requests import Request

    from data_plane.bundle.holder import BundleHolder
    from data_plane.credentials import CredentialResolver
    from data_plane.metrics import DataPlaneMetrics
    from data_plane.outbox import EventOutbox


@dataclass(frozen=True)
class Runtime:
    holder: BundleHolder
    outbox: EventOutbox
    credentials: CredentialResolver
    http_client: httpx.AsyncClient
    metrics: DataPlaneMetrics
    budgets: BudgetBackend = field(default_factory=NoBudgetBackend)


def runtime_of(request: Request) -> Runtime:
    return cast("Runtime", request.state.runtime)
