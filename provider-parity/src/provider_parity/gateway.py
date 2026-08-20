from __future__ import annotations

from dataclasses import dataclass

import httpx

from provider_parity.drivers.base import Connection

OK = 200


@dataclass(frozen=True)
class Gateway:
    base_url: str
    api_key: str
    request_timeout_seconds: float = 60

    def connection(self, endpoint: str) -> Connection:
        suffix = "/inf" if endpoint == "messages" else "/inf/v1"
        return Connection(
            base_url=f"{self.base_url.rstrip('/')}{suffix}",
            api_key=self.api_key,
            auth="bearer",
            headers={},
            route="gateway",
            timeout_seconds=self.request_timeout_seconds,
        )

    def require_ready(self) -> None:
        try:
            response = httpx.get(f"{self.base_url.rstrip('/')}/readyz", timeout=5)
        except httpx.HTTPError as error:
            message = f"gateway at {self.base_url} is not reachable: {error}"
            raise RuntimeError(message) from error
        if response.status_code != OK:
            message = f"gateway at {self.base_url} is not ready: HTTP {response.status_code}"
            raise RuntimeError(message)
