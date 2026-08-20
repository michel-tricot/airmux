from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from provider_parity.models import Case, Observation, Transport


@dataclass(frozen=True)
class Connection:
    base_url: str
    api_key: str
    auth: str
    headers: dict[str, str]
    route: Literal["direct", "gateway"]


def is_gateway_auth_failure(connection: Connection, status_code: int) -> bool:
    return connection.route == "gateway" and status_code in {401, 403}


class SDKDriver(ABC):
    id: str
    endpoints: frozenset[str]

    @abstractmethod
    def execute(self, connection: Connection, endpoint: str, model: str, case: Case, transport: Transport) -> Observation: ...
