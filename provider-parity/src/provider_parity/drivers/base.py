from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from provider_parity.models import Case, Observation, Transport

UNAUTHORIZED = 401
FORBIDDEN = 403
NOT_FOUND = 404


@dataclass(frozen=True)
class Connection:
    base_url: str
    api_key: str
    auth: str
    headers: dict[str, str]
    route: Literal["direct", "gateway"]
    timeout_seconds: float = 60


def access_error(connection: Connection, status_code: int) -> str | None:
    if status_code in {UNAUTHORIZED, FORBIDDEN}:
        return f"{connection.route}_authentication"
    if connection.route == "direct" and status_code == NOT_FOUND:
        return "direct_model_access"
    return None


class SDKDriver(ABC):
    id: str
    endpoints: frozenset[str]

    @abstractmethod
    def execute(self, connection: Connection, endpoint: str, model: str, case: Case, transport: Transport) -> Observation: ...
