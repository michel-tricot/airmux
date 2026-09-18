from __future__ import annotations

import asyncio

import httpx
import pytest
import respx
from conftest import MODEL, ORG, PROVIDER, WORKSPACE, make_bundle, make_credential, make_key, make_outbox, mock_control_plane, read_and_close_outbox
from starlette.testclient import TestClient

from airmux_runtime.secrets import (
    FileStoreConfig,
    MemoryStoreConfig,
    Secret,
    SecretStoreUnavailableError,
)
from contract import Catalog, uuid7
from data_plane.app import create_app
from data_plane.bundle import BundleSnapshot, RemoteBundleConfig
from data_plane.cache import CachedBundles, write_cached_bundles
from data_plane.canonical import CanonicalRequest
from data_plane.config import Config, DevNullOutboxConfig, SqliteOutboxConfig
from data_plane.control_plane_link import ControlPlaneLink
from data_plane.credentials import CredentialResolver
from data_plane.metrics import DataPlaneMetrics
from data_plane.policy import Allow, Deny, evaluate

OTHER_WORKSPACE = uuid7()


def _recorded(tmp_path, http_client):
    """The events the data plane buffered, read straight from its outbox."""
    return read_and_close_outbox(make_outbox(tmp_path, http_client))


async def value_of(resolver, entry) -> str:
    """The resolved value, with the absent case as a failed assertion rather than an attribute error."""
    secret = await resolver.fetch(entry)
    assert secret is not None
    return secret.reveal()


def snap(*credentials):
    bundle = make_bundle(catalog=Catalog(providers=(PROVIDER,), models=(MODEL,), credentials=tuple(credentials)), org=ORG)
    return BundleSnapshot.from_bundle(bundle)


def decide(*credentials, workspace=WORKSPACE):
    request = CanonicalRequest(model="gpt-test", messages=[{"role": "user", "content": "hi"}])
    key = make_key("k1", org=ORG, workspace=workspace)[1]
    return evaluate(request, key, snap(*credentials))


def test_a_workspace_key_wins_over_the_org_one():
    workspace_key = make_credential(workspace=WORKSPACE, name="mine")
    org_key = make_credential(name="shared")
    decision = decide(org_key, workspace_key)
    assert isinstance(decision, Allow)
    assert [c.ref.name for c in decision.candidates] == ["mine"]


def test_a_workspace_with_no_key_falls_back_to_the_org():
    org_key = make_credential(name="shared")
    decision = decide(org_key, make_credential(workspace=OTHER_WORKSPACE, name="theirs"))
    assert isinstance(decision, Allow)
    assert [c.ref.name for c in decision.candidates] == ["shared"]


def test_an_org_with_no_key_falls_back_to_the_platform():
    decision = decide(make_credential(org=None, name="operator"))
    assert isinstance(decision, Allow)
    assert [c.ref.name for c in decision.candidates] == ["operator"]


def test_a_tier_with_a_key_is_the_tier():
    """Cascading happens on an empty tier and never on a failing one: falling through when a
    workspace key is broken would move the org's spend onto the platform account unasked."""
    decision = decide(make_credential(org=None, name="platform"), make_credential(workspace=WORKSPACE, name="mine"))
    assert isinstance(decision, Allow)
    assert [c.ref.name for c in decision.candidates] == ["mine"]


def test_no_key_anywhere_is_denied():
    assert decide() == Deny(code="credential_unavailable", status=402)


def test_candidates_come_back_in_try_order():
    """Priority first, then name, so the order is total and two data planes agree on it."""
    decision = decide(
        make_credential(name="c", priority=10),
        make_credential(name="a", priority=50),
        make_credential(name="b", priority=10),
    )
    assert isinstance(decision, Allow)
    assert [c.ref.name for c in decision.candidates] == ["b", "c", "a"]


def test_a_key_for_another_provider_is_not_a_candidate():
    other = PROVIDER.model_copy(update={"provider_id": "other"})
    credential = make_credential(service="other")
    bundle = make_bundle(
        catalog=Catalog(
            providers=(PROVIDER, other),
            models=(MODEL,),
            credentials=(credential,),
        ),
        org=ORG,
    )
    request = CanonicalRequest(model="gpt-test", messages=[{"role": "user", "content": "hi"}])
    key = make_key("k1", org=ORG, workspace=WORKSPACE)[1]

    assert evaluate(request, key, BundleSnapshot.from_bundle(bundle)) == Deny(code="credential_unavailable", status=402)


async def test_the_resolver_fetches_and_caches():
    store = MemoryStoreConfig().build()
    entry = make_credential()
    await store.put(entry.ref, Secret("sk-value"))
    resolver = CredentialResolver(store, DataPlaneMetrics())
    assert await value_of(resolver, entry) == "sk-value"
    await store.delete(entry.ref)
    assert await value_of(resolver, entry) == "sk-value"


async def test_a_rotation_busts_the_cache_without_an_invalidation_message():
    """The version is the cache key, so a rotated credential arriving in the next bundle is fetched
    again on its first use rather than at the end of the TTL."""
    store = MemoryStoreConfig().build()
    entry = make_credential()
    await store.put(entry.ref, Secret("first"))
    resolver = CredentialResolver(store, DataPlaneMetrics())
    assert await value_of(resolver, entry) == "first"
    await store.put(entry.ref, Secret("second"))
    rotated = make_credential(version=2, secret_id=entry.ref.secret_id)
    assert await value_of(resolver, rotated) == "second"


async def test_a_credential_with_no_value_resolves_to_nothing():
    """The row and the value live in two systems, so a bundle can name a credential the store never
    received. That is a fact about the credential, so it is cached briefly."""
    resolver = CredentialResolver(MemoryStoreConfig().build(), DataPlaneMetrics())
    assert await resolver.fetch(make_credential()) is None


async def test_an_unavailable_store_raises_and_is_not_cached():
    """Infrastructure being down must not be remembered as a missing key, or a store that recovers
    stays invisible for the length of the negative TTL."""

    class Broken:
        kind = "broken"

        def __init__(self):
            self.calls = 0

        async def get(self, ref):
            self.calls += 1
            raise SecretStoreUnavailableError(ref, "down")

    store = Broken()
    resolver = CredentialResolver(store, DataPlaneMetrics())
    entry = make_credential()
    for _ in range(2):
        with pytest.raises(SecretStoreUnavailableError):
            await resolver.fetch(entry)
    assert store.calls == 2


async def test_forget_drops_a_value_upstream_rejected():
    store = MemoryStoreConfig().build()
    entry = make_credential()
    await store.put(entry.ref, Secret("stale"))
    resolver = CredentialResolver(store, DataPlaneMetrics())
    await resolver.fetch(entry)
    await store.put(entry.ref, Secret("fresh"))
    resolver.forget(entry)
    assert await value_of(resolver, entry) == "fresh"


BYOK_RESPONSE = {
    "id": "chatcmpl-1",
    "model": "gpt-real",
    "choices": [{"index": 0, "message": {"role": "assistant", "content": "hi"}, "finish_reason": "stop"}],
    "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
}


def _byok_app(tmp_path, credentials):
    """A booted data plane whose bundle names the given credentials.

    The file store is what makes this a real end-to-end test rather than a wiring one: the test and
    the app reach the same values through the same root the way two processes would, instead of
    sharing an object the app never built.
    """
    caller_token, entry = make_key(org=ORG, workspace=WORKSPACE)
    catalog = Catalog(providers=(PROVIDER,), models=(MODEL,), credentials=tuple(credentials))
    bundle = make_bundle(keys=[entry], catalog=catalog, org=ORG)
    write_cached_bundles(tmp_path, CachedBundles(bundles=[bundle]))
    store_config = FileStoreConfig(path=tmp_path / "secrets")
    control_plane = ControlPlaneLink(url="http://cp.test", management_key="dp-token")
    config = Config(
        bundle=RemoteBundleConfig(control_plane=control_plane, cache_dir=tmp_path),
        secrets=store_config,
        events=SqliteOutboxConfig(control_plane=control_plane, cache_dir=tmp_path),
    )
    return create_app(config), caller_token, store_config.build()


def _complete(app, caller_token):
    mock_control_plane()
    with TestClient(app) as client:
        return client.post(
            "/inf/v1/chat/completions",
            headers={"Authorization": f"Bearer {caller_token}"},
            json={"model": "gpt-test", "messages": [{"role": "user", "content": "hi"}]},
        )


@respx.mock
def test_one_data_plane_serves_two_org_bundles(tmp_path):
    other_org = uuid7()
    other_workspace = uuid7()
    first_token, first_key = make_key("first", org=ORG, workspace=WORKSPACE)
    second_token, second_key = make_key("second", org=other_org, workspace=other_workspace)
    platform = make_credential(org=None, name="platform")
    catalog = Catalog(providers=(PROVIDER,), models=(MODEL,), credentials=(platform,))
    write_cached_bundles(
        tmp_path,
        CachedBundles(
            bundles=[
                make_bundle(keys=[first_key], catalog=catalog, org=ORG),
                make_bundle(keys=[second_key], catalog=catalog, org=other_org),
            ],
        ),
    )
    store_config = FileStoreConfig(path=tmp_path / "secrets")
    asyncio.run(store_config.build().put(platform.ref, Secret("sk-platform")))
    control_plane = ControlPlaneLink(url="http://cp.test", management_key="dp-token")
    config = Config(
        bundle=RemoteBundleConfig(control_plane=control_plane, cache_dir=tmp_path),
        secrets=store_config,
        events=DevNullOutboxConfig(),
    )
    mock_control_plane()
    route = respx.post("https://api.openai.com/v1/chat/completions").mock(return_value=httpx.Response(200, json=BYOK_RESPONSE))

    with TestClient(create_app(config)) as client:
        body = {"model": "gpt-test", "messages": [{"role": "user", "content": "hi"}]}
        assert client.post("/inf/v1/chat/completions", headers={"Authorization": f"Bearer {first_token}"}, json=body).status_code == 200
        assert client.post("/inf/v1/chat/completions", headers={"Authorization": f"Bearer {second_token}"}, json=body).status_code == 200
    assert [call.request.headers["authorization"] for call in route.calls] == ["Bearer sk-platform", "Bearer sk-platform"]


@respx.mock
def test_the_workspace_key_is_what_reaches_the_provider(tmp_path):
    """The point of the whole feature, proved where it matters: on the wire to the upstream."""
    workspace_key = make_credential(workspace=WORKSPACE, name="mine")
    org_key = make_credential(name="shared")
    app, caller_token, store = _byok_app(tmp_path, [org_key, workspace_key])
    asyncio.run(store.put(workspace_key.ref, Secret("sk-workspace")))
    asyncio.run(store.put(org_key.ref, Secret("sk-org")))
    route = respx.post("https://api.openai.com/v1/chat/completions").mock(return_value=httpx.Response(200, json=BYOK_RESPONSE))

    response = _complete(app, caller_token)
    assert response.status_code == 200, response.text
    assert route.calls.last.request.headers["authorization"] == "Bearer sk-workspace"


@respx.mock
def test_a_credential_with_no_value_fails_the_request(tmp_path):
    """It never falls through to the platform key: a missing value must not move an org's spend."""
    app, caller_token, store = _byok_app(tmp_path, [make_credential(workspace=WORKSPACE), make_credential(org=None, name="platform")])
    asyncio.run(store.put(make_credential(org=None, name="platform").ref, Secret("sk-platform")))
    respx.post("https://api.openai.com/v1/chat/completions").mock(return_value=httpx.Response(200, json=BYOK_RESPONSE))
    assert _complete(app, caller_token).status_code == 502


@respx.mock
def test_a_missing_credential_falls_through_only_within_its_selected_tier(tmp_path):
    missing = make_credential(workspace=WORKSPACE, name="first", priority=10)
    working = make_credential(workspace=WORKSPACE, name="second", priority=20)
    platform = make_credential(org=None, name="platform", priority=1)
    app, caller_token, store = _byok_app(tmp_path, [missing, working, platform])
    asyncio.run(store.put(working.ref, Secret("sk-working")))
    asyncio.run(store.put(platform.ref, Secret("sk-platform")))
    route = respx.post("https://api.openai.com/v1/chat/completions").mock(return_value=httpx.Response(200, json=BYOK_RESPONSE))

    response = _complete(app, caller_token)

    assert response.status_code == 200
    assert route.calls.last.request.headers["authorization"] == "Bearer sk-working"


@respx.mock
@pytest.mark.parametrize(("failed_status", "metered"), [(401, "credential_rejected"), (429, "rate_limited")])
def test_a_rejected_or_limited_credential_fails_over_within_the_tier(tmp_path, http_client, failed_status, metered):
    first = make_credential(workspace=WORKSPACE, name="first", priority=10)
    second = make_credential(workspace=WORKSPACE, name="second", priority=20)
    app, caller_token, store = _byok_app(tmp_path, [first, second])
    asyncio.run(store.put(first.ref, Secret("sk-first")))
    asyncio.run(store.put(second.ref, Secret("sk-second")))

    def upstream(request: httpx.Request) -> httpx.Response:
        if request.headers["authorization"] == "Bearer sk-first":
            return httpx.Response(failed_status, json={"error": {"code": "rejected", "message": "try another"}})
        return httpx.Response(200, json=BYOK_RESPONSE)

    route = respx.post("https://api.openai.com/v1/chat/completions").mock(side_effect=upstream)

    response = _complete(app, caller_token)

    assert response.status_code == 200
    assert [call.request.headers["authorization"] for call in route.calls] == ["Bearer sk-first", "Bearer sk-second"]
    assert [event.status for event in _recorded(tmp_path, http_client)] == [metered, "ok"]


@respx.mock
def test_an_all_limited_tier_preserves_the_provider_error_on_the_next_request(tmp_path):
    credential = make_credential(workspace=WORKSPACE, name="only")
    app, caller_token, store = _byok_app(tmp_path, [credential])
    asyncio.run(store.put(credential.ref, Secret("sk-workspace")))
    route = respx.post("https://api.openai.com/v1/chat/completions").mock(
        return_value=httpx.Response(429, json={"error": {"code": "rate_limit_exceeded", "message": "slow down"}})
    )
    mock_control_plane()
    body = {"model": "gpt-test", "max_tokens": 8, "messages": [{"role": "user", "content": "hi"}]}
    with TestClient(app) as client:
        responses = [
            client.post("/inf/v1/messages", headers={"Authorization": f"Bearer {caller_token}"}, json=body),
            client.post("/inf/v1/messages", headers={"Authorization": f"Bearer {caller_token}"}, json=body),
        ]

    assert [response.status_code for response in responses] == [429, 429]
    assert [response.json() for response in responses] == [
        {"type": "error", "error": {"type": "rate_limit_exceeded", "message": "slow down"}},
        {"type": "error", "error": {"type": "rate_limit_exceeded", "message": "slow down"}},
    ]
    assert len(route.calls) == 2


@respx.mock
def test_an_upstream_rejection_invalidates_the_cached_secret(tmp_path):
    credential = make_credential(workspace=WORKSPACE, name="only")
    app, caller_token, store = _byok_app(tmp_path, [credential])
    asyncio.run(store.put(credential.ref, Secret("sk-stale")))

    def upstream(request: httpx.Request) -> httpx.Response:
        if request.headers["authorization"] == "Bearer sk-stale":
            return httpx.Response(401, json={"error": {"code": "invalid_key", "message": "stale"}})
        return httpx.Response(200, json=BYOK_RESPONSE)

    route = respx.post("https://api.openai.com/v1/chat/completions").mock(side_effect=upstream)
    mock_control_plane()
    body = {"model": "gpt-test", "messages": [{"role": "user", "content": "hi"}]}
    with TestClient(app) as client:
        first = client.post("/inf/v1/chat/completions", headers={"Authorization": f"Bearer {caller_token}"}, json=body)
        asyncio.run(store.put(credential.ref, Secret("sk-fresh")))
        second = client.post("/inf/v1/chat/completions", headers={"Authorization": f"Bearer {caller_token}"}, json=body)

    assert first.status_code == 401
    assert second.status_code == 200
    assert [call.request.headers["authorization"] for call in route.calls] == ["Bearer sk-stale", "Bearer sk-fresh"]


@respx.mock
def test_a_request_with_no_credential_anywhere_is_denied(tmp_path):
    app, caller_token, _ = _byok_app(tmp_path, [])
    assert _complete(app, caller_token).status_code == 402


@respx.mock
def test_the_usage_event_names_the_credential_that_paid(tmp_path, http_client):
    """Per-key attribution is what lets an operator separate a tenant's spend from the platform's,
    and it is the only channel a credential's health travels back on."""
    workspace_key = make_credential(workspace=WORKSPACE, name="mine")
    app, caller_token, store = _byok_app(tmp_path, [workspace_key])
    asyncio.run(store.put(workspace_key.ref, Secret("sk-workspace")))
    respx.post("https://api.openai.com/v1/chat/completions").mock(return_value=httpx.Response(200, json=BYOK_RESPONSE))

    assert _complete(app, caller_token).status_code == 200
    event = _recorded(tmp_path, http_client)[0]
    assert event.credential_id == workspace_key.ref.secret_id
    assert event.credential_scope == "workspace"
    assert event.status == "ok"


@respx.mock
@pytest.mark.parametrize(
    ("upstream_status", "metered"),
    [(401, "credential_rejected"), (403, "credential_rejected"), (429, "rate_limited"), (500, "upstream_error")],
)
def test_the_event_says_whether_the_key_or_the_provider_failed(tmp_path, http_client, upstream_status, metered):
    """A provider outage says nothing about whether the key is good, so only the statuses that are
    facts about the credential are split out."""
    workspace_key = make_credential(workspace=WORKSPACE, name="mine")
    app, caller_token, store = _byok_app(tmp_path, [workspace_key])
    asyncio.run(store.put(workspace_key.ref, Secret("sk-workspace")))
    respx.post("https://api.openai.com/v1/chat/completions").mock(return_value=httpx.Response(upstream_status, json={"error": "no"}))

    assert _complete(app, caller_token).status_code == upstream_status
    assert _recorded(tmp_path, http_client)[0].status == metered
