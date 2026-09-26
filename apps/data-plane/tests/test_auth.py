from __future__ import annotations

from datetime import UTC, datetime, timedelta
from functools import partial

import pytest
from conftest import make_bundle as _make_bundle
from conftest import make_key as _make_key
from starlette.requests import Request

from contract import uuid7
from data_plane.auth import authenticate, authenticate_request, index_keys
from data_plane.bundle.holder import BundleHolder, BundleSet
from data_plane.canonical import GatewayErrorCode
from data_plane.errors import RequestRejectedError
from data_plane.metrics import DataPlaneMetrics

ORG_A = uuid7()
make_bundle = partial(_make_bundle, org=ORG_A)
make_key = partial(_make_key, org=ORG_A)


def test_first_bundle_arriving_during_authentication_does_not_reject_valid_key():
    token, entry = make_key("k1")
    accepted = BundleSet.from_bundles((make_bundle([entry]),))

    class RecoveringHolder(BundleHolder):
        @property
        def current(self) -> BundleSet:
            current = super().current
            self.swap(accepted, source="local")
            return current

    holder = RecoveringHolder(DataPlaneMetrics())
    request = Request({"type": "http", "headers": [(b"authorization", f"Bearer {token}".encode())]})

    with pytest.raises(RequestRejectedError) as rejected:
        authenticate_request(request, holder)

    assert rejected.value.status == 503
    assert rejected.value.code == GatewayErrorCode.bundle_unavailable

    holder.swap(accepted, source="local")
    key, snapshot = authenticate_request(request, holder)
    assert key == entry
    assert snapshot == accepted.snapshots[ORG_A]


def test_valid_opaque_token_authenticates():
    token, entry = make_key("k1")
    key = authenticate(token, index_keys(make_bundle([entry])), datetime.now(tz=UTC))
    assert key is not None
    assert key.key_id == entry.key_id


def test_token_absent_from_bundle_rejected():
    token, _ = make_key("k1")
    _, other = make_key("k2")
    now = datetime.now(tz=UTC)
    assert authenticate(token, index_keys(make_bundle([other])), now) is None
    assert authenticate(token, index_keys(make_bundle([])), now) is None


def test_tampered_token_rejected():
    token, entry = make_key("k1")
    index = index_keys(make_bundle([entry]))
    now = datetime.now(tz=UTC)
    assert authenticate(token[:-1], index, now) is None
    assert authenticate(token + "x", index, now) is None


def test_control_plane_management_key_rejected():
    _, entry = make_key("k1")
    assert authenticate("sk-cp-anything", index_keys(make_bundle([entry])), datetime.now(tz=UTC)) is None


def test_garbage_and_empty_rejected():
    _, entry = make_key("k1")
    index = index_keys(make_bundle([entry]))
    now = datetime.now(tz=UTC)
    assert authenticate("not-a-token", index, now) is None
    assert authenticate("", index, now) is None


def test_expired_token_is_rejected():
    token, entry = make_key("k1")
    now = datetime.now(tz=UTC)
    expired = entry.model_copy(update={"expires_at": now - timedelta(seconds=1)})

    assert authenticate(token, index_keys(make_bundle([expired])), now) is None


def test_unexpired_token_authenticates():
    token, entry = make_key("k1")
    now = datetime.now(tz=UTC)
    live = entry.model_copy(update={"expires_at": now + timedelta(seconds=1)})

    assert authenticate(token, index_keys(make_bundle([live])), now) == live
