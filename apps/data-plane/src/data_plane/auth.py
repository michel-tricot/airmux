from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from contract import INFERENCE_TOKEN_PREFIX, PLAYGROUND_COOKIE, token_hash
from data_plane.canonical import GatewayErrorCode
from data_plane.errors import RequestRejectedError

if TYPE_CHECKING:
    from collections.abc import Mapping

    from starlette.requests import Request

    from contract import BundleV1, KeyEntry
    from data_plane.bundle.holder import BundleHolder, BundleSnapshot


def index_keys(bundle: BundleV1) -> dict[str, KeyEntry]:
    return {k.token_hash: k for k in bundle.keys}


def authenticate(bearer: str, index: Mapping[str, KeyEntry], now: datetime) -> KeyEntry | None:
    """Hash the presented bearer and look it up; absence from the bundle is invalidity."""
    if not bearer.startswith(INFERENCE_TOKEN_PREFIX):
        return None
    key = index.get(token_hash(bearer))
    if key is None or (key.expires_at is not None and key.expires_at <= now):
        return None
    return key


def authenticate_request(request: Request, holder: BundleHolder) -> tuple[KeyEntry, BundleSnapshot]:
    bundle_set = holder.current
    if not holder.initialized:
        raise RequestRejectedError(503, GatewayErrorCode.bundle_unavailable)
    token = _request_token(request)
    key = authenticate(token, bundle_set.key_index, datetime.now(tz=UTC))
    if key is None:
        raise RequestRejectedError(401, GatewayErrorCode.invalid_token)
    return key, bundle_set.snapshots[key.org_id]


def _request_token(request: Request) -> str:
    scheme, _, bearer = request.headers.get("authorization", "").partition(" ")
    if scheme.casefold() == "bearer" and (token := bearer.strip()):
        return token
    if token := request.headers.get("x-api-key", "").strip():
        return token
    token = request.cookies.get(PLAYGROUND_COOKIE, "")
    if not token:
        raise RequestRejectedError(401, GatewayErrorCode.missing_bearer_token)
    if request.headers.get("x-requested-with") is None:
        raise RequestRejectedError(403, GatewayErrorCode.missing_requested_with)
    if request.headers.get("sec-fetch-site") not in (None, "same-origin", "none"):
        raise RequestRejectedError(403, GatewayErrorCode.cross_site_request)
    return token
