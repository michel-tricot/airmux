from __future__ import annotations

from http import HTTPStatus

import aiohttp
from pydantic import BaseModel, ConfigDict, Field


class ControlPlaneLink(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    url: str = Field(min_length=1)
    management_key: str = Field(min_length=1)


async def complete_response(response: aiohttp.ClientResponse) -> None:
    await response.read()
    if not HTTPStatus.OK <= response.status < HTTPStatus.MULTIPLE_CHOICES:
        raise aiohttp.ClientResponseError(
            response.request_info, response.history, status=response.status, message=response.reason or "", headers=response.headers
        )
