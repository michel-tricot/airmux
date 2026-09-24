from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, cast

from data_plane.budgets import BudgetBackend, NoBudgetBackend

if TYPE_CHECKING:
    import aiohttp
    from starlette.requests import Request

    from data_plane.bundle.holder import BundleHolder
    from data_plane.credentials import CredentialResolver
    from data_plane.metrics import DataPlaneMetrics
    from data_plane.outbox import EventOutbox
    from data_plane.provider_http_client import ProviderHttpClient


@dataclass(frozen=True)
class Runtime:
    holder: BundleHolder
    outbox: EventOutbox
    credentials: CredentialResolver
    http_client: aiohttp.ClientSession
    provider_http_client: ProviderHttpClient
    metrics: DataPlaneMetrics
    budgets: BudgetBackend = field(default_factory=NoBudgetBackend)


def runtime_of(request: Request) -> Runtime:
    return cast("Runtime", request.state.runtime)
