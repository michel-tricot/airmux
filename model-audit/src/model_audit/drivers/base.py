from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from model_audit.models import Case, ClientMode, Observation, Outcome, Transport

UNAUTHORIZED = 401
FORBIDDEN = 403
NOT_FOUND = 404
TOO_MANY_REQUESTS = 429
SERVER_ERROR = 500
REJECTION_STATUSES = {400, 404, 422}


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


def status_outcome(connection: Connection, status_code: int) -> Outcome:
    if access_error(connection, status_code) is not None:
        return "inconclusive"
    if status_code == TOO_MANY_REQUESTS or (connection.route == "direct" and status_code >= SERVER_ERROR):
        return "transient"
    return "rejected" if status_code in REJECTION_STATUSES else "error"


class ClientDriver(ABC):
    id: str
    mode: ClientMode
    endpoints: frozenset[str]

    @abstractmethod
    def execute(self, connection: Connection, endpoint: str, model: str, case: Case, transport: Transport) -> Observation: ...
