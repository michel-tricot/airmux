from __future__ import annotations

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
    key = authenticate(token, index_keys(make_bundle([entry])))
    assert key is not None
    assert key.key_id == "k1"


def test_token_absent_from_bundle_rejected():
    token, _ = make_key("k1")
    _, other = make_key("k2")
    assert authenticate(token, index_keys(make_bundle([other]))) is None
    assert authenticate(token, index_keys(make_bundle([]))) is None


def test_tampered_token_rejected():
    token, entry = make_key("k1")
    index = index_keys(make_bundle([entry]))
    assert authenticate(token[:-1], index) is None
    assert authenticate(token + "x", index) is None


def test_management_prefixed_token_rejected():
    _, entry = make_key("k1")
    assert authenticate("sk-mgmt-anything", index_keys(make_bundle([entry]))) is None


def test_garbage_and_empty_rejected():
    _, entry = make_key("k1")
    index = index_keys(make_bundle([entry]))
    assert authenticate("not-a-token", index) is None
    assert authenticate("", index) is None
