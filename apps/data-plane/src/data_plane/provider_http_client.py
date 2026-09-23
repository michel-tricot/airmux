from __future__ import annotations

import os
from datetime import timedelta
from typing import TYPE_CHECKING, NoReturn, Self

import aiohttp
from pyreqwest.client import Client, ClientBuilder
from pyreqwest.exceptions import NetworkError, RequestTimeoutError
from pyreqwest.proxy import ProxyBuilder

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Mapping

    from pyreqwest.request import RequestBuilder, StreamRequest
    from pyreqwest.response import Response

    from data_plane.config import HttpConfig


class ProviderResponse:
    def __init__(self, response: Response) -> None:
        self.status = response.status
        self._response = response

    async def read(self) -> bytes:
        try:
            return bytes(await self._response.bytes())
        except RequestTimeoutError:
            raise
        except NetworkError as error:
            _raise_network_error(error)

    async def iter_any(self) -> AsyncIterator[bytes]:
        reader = self._response.body_reader
        try:
            while chunk := await reader.read_chunk():
                yield bytes(chunk)
        except RequestTimeoutError:
            raise
        except NetworkError as error:
            _raise_network_error(error)


class ProviderRequest:
    def __init__(self, builder: RequestBuilder, *, stream: bool):
        self._builder = builder
        self._stream = stream
        self._stream_request: StreamRequest | None = None

    async def __aenter__(self) -> ProviderResponse:
        try:
            if self._stream:
                self._stream_request = self._builder.streamed_read_buffer_limit(1).build_streamed()
                response = await self._stream_request.__aenter__()
            else:
                response = await self._builder.build().send()
            return ProviderResponse(response)
        except RequestTimeoutError:
            raise
        except NetworkError as error:
            _raise_network_error(error)

    async def __aexit__(self, *_args: object) -> None:
        if self._stream_request is not None:
            await self._stream_request.__aexit__(*_args)


class ProviderHttpClient:
    def __init__(self, client: Client) -> None:
        self._client = client

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *_args: object) -> None:
        await self._client.close()

    def request(self, method: str, url: str, *, headers: Mapping[str, str], data: bytes | None = None, stream: bool = False) -> ProviderRequest:
        builder = self._client.request(method, url).headers(headers).error_for_status(False)
        if data is not None:
            builder = builder.body_bytes(data)
        return ProviderRequest(builder, stream=stream)


def _raise_network_error(error: NetworkError) -> NoReturn:
    raise aiohttp.ClientConnectionError(str(error)) from error


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
