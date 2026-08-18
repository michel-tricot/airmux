from __future__ import annotations

from datetime import UTC, datetime, timedelta
from functools import partial

from conftest import make_bundle as _make_bundle
from conftest import make_key as _make_key

from contract import uuid7
from data_plane.auth import authenticate, index_keys

ORG_A = uuid7()
make_bundle = partial(_make_bundle, org=ORG_A)
make_key = partial(_make_key, org=ORG_A)


def test_valid_opaque_token_authenticates():
    token, entry = make_key("k1")
    key = authenticate(token, index_keys(make_bundle([entry])), datetime.now(tz=UTC))
    assert key is not None
    assert key.key_id == "k1"


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


def test_control_plane_access_key_rejected():
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
