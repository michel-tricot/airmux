from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from model_audit.models import Case, ClientMode, Observation, Outcome, Transport

UNAUTHORIZED = 401
FORBIDDEN = 403
NOT_FOUND = 404
TOO_MANY_REQUESTS = 429
SERVER_ERROR = 500
REJECTION_STATUSES = {400, 404, 422}
GATEWAY_AUTHENTICATION_CODES = frozenset({"missing_bearer_token", "missing_requested_with", "cross_site_request", "invalid_token"})
PROVIDER_BILLING_CODES = frozenset({"billing_hard_limit_reached", "credit_balance_exhausted", "insufficient_quota"})


@dataclass(frozen=True)
class Connection:
    base_url: str
    api_key: str
    auth: str
    headers: dict[str, str]
    route: Literal["direct", "gateway"]
    timeout_seconds: float = 60
    param_aliases: dict[str, str] = field(default_factory=dict)


def access_error(connection: Connection, status_code: int, error_code: str | None = None) -> str | None:
    if status_code == TOO_MANY_REQUESTS and error_code in PROVIDER_BILLING_CODES:
        return "provider_billing_access"
    if connection.route == "direct" and status_code == UNAUTHORIZED:
        return "direct_authentication"
    if connection.route == "gateway" and status_code in {UNAUTHORIZED, FORBIDDEN} and error_code in GATEWAY_AUTHENTICATION_CODES:
        return "gateway_authentication"
    if connection.route == "direct" and status_code == NOT_FOUND:
        return "direct_model_access"
    return None


def status_outcome(connection: Connection, status_code: int, error_code: str | None = None) -> Outcome:
    if access_error(connection, status_code, error_code) is not None:
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
