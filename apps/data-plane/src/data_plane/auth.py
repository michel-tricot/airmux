from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from contract import INFERENCE_TOKEN_PREFIX, PLAYGROUND_COOKIE, token_hash
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
    if not bundle_set.snapshots:
        raise RequestRejectedError(503, "bundle_unavailable")
    auth_header = request.headers.get("authorization", "")
    scheme, separator, value = auth_header.partition(" ")
    if separator and scheme.casefold() == "bearer":
        token = value.strip()
    else:
        token = request.cookies.get(PLAYGROUND_COOKIE, "")
        if not token:
            raise RequestRejectedError(401, "missing_bearer_token")
        if request.headers.get("x-requested-with") is None:
            raise RequestRejectedError(403, "missing_requested_with")
        if request.headers.get("sec-fetch-site") not in (None, "same-origin", "none"):
            raise RequestRejectedError(403, "cross_site_request")
    key = authenticate(token, bundle_set.key_index, datetime.now(tz=UTC))
    if key is None:
        raise RequestRejectedError(401, "invalid_token")
    return key, bundle_set.snapshots[key.org_id]
