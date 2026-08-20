from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from provider_parity.models import Case, Observation, Transport


@dataclass(frozen=True)
class Connection:
    base_url: str
    api_key: str
    auth: str
    headers: dict[str, str]


class SDKDriver(ABC):
    id: str
    endpoints: frozenset[str]

    @abstractmethod
    def execute(self, connection: Connection, endpoint: str, model: str, case: Case, transport: Transport) -> Observation: ...
