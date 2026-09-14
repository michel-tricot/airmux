from __future__ import annotations

import ssl
import urllib.request
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

if TYPE_CHECKING:
    from collections.abc import Mapping

CONTEXT = ssl.create_default_context()


def fetch_bytes(url: str, headers: Mapping[str, str], *, timeout: int) -> bytes:
    if urlsplit(url).scheme != "https":
        message = f"catalog acquisition requires HTTPS: {url}"
        raise ValueError(message)
    request = urllib.request.Request(url, headers=dict(headers))  # noqa: S310 URL scheme is restricted above
    with urllib.request.urlopen(request, timeout=timeout, context=CONTEXT) as response:  # noqa: S310 URL scheme is restricted above
        return response.read()


def fetch_text(url: str, headers: Mapping[str, str], *, timeout: int) -> str:
    return fetch_bytes(url, headers, timeout=timeout).decode("utf-8", "replace")
