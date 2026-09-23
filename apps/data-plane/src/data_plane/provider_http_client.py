from __future__ import annotations

import os
from datetime import timedelta
from typing import TYPE_CHECKING, Self

import aiohttp
from pyreqwest.client import Client, ClientBuilder
from pyreqwest.exceptions import NetworkError
from pyreqwest.proxy import ProxyBuilder

if TYPE_CHECKING:
    from collections.abc import Mapping

    from pyreqwest.request import RequestBuilder
    from pyreqwest.response import Response

    from data_plane.config import HttpConfig


class ProviderResponse:
    def __init__(self, response: Response) -> None:
        self.status = response.status
        self._response = response

    async def read(self) -> bytes:
        try:
            return bytes(await self._response.bytes())
        except NetworkError as error:
            raise aiohttp.ClientConnectionError(str(error)) from error


class ProviderRequest:
    def __init__(self, builder: RequestBuilder):
        self._builder = builder

    async def __aenter__(self) -> ProviderResponse:
        try:
            return ProviderResponse(await self._builder.build().send())
        except NetworkError as error:
            raise aiohttp.ClientConnectionError(str(error)) from error

    async def __aexit__(self, *_args: object) -> None:
        return None


class ProviderHttpClient:
    def __init__(self, client: Client) -> None:
        self._client = client

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *_args: object) -> None:
        await self._client.close()

    def request(self, method: str, url: str, *, headers: Mapping[str, str], data: bytes | None = None) -> ProviderRequest:
        builder = self._client.request(method, url).headers(headers).error_for_status(False)
        if data is not None:
            builder = builder.body_bytes(data)
        return ProviderRequest(builder)


def _proxy_settings() -> tuple[tuple[str, str], ...]:
    return tuple(
        (scheme, proxy)
        for scheme, names in (
            ("http", ("HTTP_PROXY", "http_proxy")),
            ("https", ("HTTPS_PROXY", "https_proxy")),
        )
        if (proxy := next((os.environ[name] for name in names if os.environ.get(name)), ""))
    )


def build_provider_http_client(config: HttpConfig) -> ProviderHttpClient:
    proxies = _proxy_settings()
    no_proxy = os.environ.get("NO_PROXY") or os.environ.get("no_proxy")
    builder = (
        ClientBuilder()
        .max_connections(config.max_connections)
        .connect_timeout(timedelta(seconds=5))
        .read_timeout(timedelta(seconds=120))
        .pool_idle_timeout(timedelta(seconds=15))
        .pool_max_idle_per_host(config.max_connections)
        .follow_redirects(False)
        .no_proxy()
    )
    for scheme, url in proxies:
        proxy = (ProxyBuilder.http if scheme == "http" else ProxyBuilder.https)(url).no_proxy(no_proxy)
        builder = builder.proxy(proxy)
    return ProviderHttpClient(builder.build())
