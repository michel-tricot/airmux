from __future__ import annotations

import asyncio
import json

import httpx
import pytest
import respx
from conftest import (
    MODEL,
    ORG,
    PLATFORM_CREDENTIAL,
    PROVIDER,
    TEXT_LOG,
    TEXT_NONSTREAM,
    WORKSPACE,
    make_bundle,
    make_credential,
    make_key,
    make_outbox,
    mock_control_plane,
)
from starlette.testclient import TestClient

from contract import Catalog, uuid7
from contract.policies import PolicyDefinition, PolicyEntry
from data_plane.bundle.holder import BundleSnapshot
from data_plane.cache import CachedBundles, write_cached_bundles
from data_plane.canonical import CanonicalRequest
from data_plane.policy import Allow, Deny, evaluate
from data_plane.routing import RoutePlan, plan_routes


def request():
    return CanonicalRequest(model=MODEL.model_id, messages=[{"role": "user", "content": "hi"}])


def policy(action, *, condition="true", workspace=WORKSPACE, target=None):
    return PolicyEntry(
        id=uuid7(),
        workspace_id=workspace,
        name="test",
        priority=100,
        definition=PolicyDefinition.model_validate({"target": target or {"kind": "all_keys"}, "condition": condition, "action": action}),
    )


def snapshot(policies, *, credentials=None):
    _, key = make_key()
    bundle = make_bundle(keys=[key], catalog=Catalog(providers=[PROVIDER], models=[MODEL], credentials=credentials or [make_credential(org=None)]))
    return key, BundleSnapshot.from_bundle(bundle.model_copy(update={"policies": tuple(policies)}))


@pytest.mark.parametrize("action", [{"kind": "byok"}, {"kind": "models", "names": ["other"]}, {"kind": "providers", "names": ["other"]}])
def test_restrictions_deny_before_upstream(action):
    key, snap = snapshot([policy(action)])
    result = evaluate(request(), key, snap)
    assert isinstance(result, Deny)
    assert result.code == "policy_denied"


def test_byok_accepts_org_credentials():
    key, snap = snapshot([policy({"kind": "byok"})], credentials=[make_credential(org=ORG)])
    assert isinstance(evaluate(request(), key, snap), Allow)


@pytest.mark.parametrize(
    "options", [{"workspace": uuid7()}, {"condition": "request_stream"}, {"target": {"kind": "selected_keys", "key_ids": ["other"]}}]
)
def test_only_matching_workspace_keys_and_conditions_are_restricted(options):
    key, snap = snapshot([policy({"kind": "byok"}, **options)])
    assert isinstance(evaluate(request(), key, snap), Allow)


def test_selected_key_targets_are_compiled_for_constant_time_membership():
    selected_key_ids = frozenset(str(uuid7()) for _ in range(1000))
    entry = policy({"kind": "byok"}, target={"kind": "selected_keys", "key_ids": sorted(selected_key_ids)})
    _, snap = snapshot([entry])

    assert snap.policy_index[WORKSPACE][0].selected_key_ids == selected_key_ids


def test_policy_index_preserves_workspace_evaluation_order():
    other_workspace = uuid7()
    later = policy({"kind": "byok"}).model_copy(update={"priority": 20})
    first = policy({"kind": "byok"}).model_copy(update={"priority": 10})
    other = policy({"kind": "byok"}, workspace=other_workspace)

    _, snap = snapshot([later, other, first])

    assert tuple(compiled.policy.id for compiled in snap.policy_index[WORKSPACE]) == (first.id, later.id)
    assert tuple(compiled.policy.id for compiled in snap.policy_index[other_workspace]) == (other.id,)


@pytest.mark.parametrize("condition", ["true", "1 / 0 > 0"])
def test_budget_does_not_enforce_yet(condition):
    key, snap = snapshot([policy({"kind": "budget", "period": "day", "amount_usd": "1", "sharing": "shared"}, condition=condition)])
    assert isinstance(evaluate(request(), key, snap), Allow)


def test_runtime_condition_errors_fail_closed():
    key, snap = snapshot([policy({"kind": "byok"}, condition="1 / 0 > 0")])
    result = plan_routes(request(), key, snap)
    assert isinstance(result, Deny)
    assert result.code == "policy_error"


def test_restrictions_intersect_regardless_of_priority():
    key, snap = snapshot([policy({"kind": "models", "names": [MODEL.model_id]}), policy({"kind": "models", "names": ["other"]})])
    assert isinstance(evaluate(request(), key, snap), Deny)


def test_fallback_priority_is_deterministic_and_unknown_backups_are_skipped():
    action = {"kind": "fallback", "models": ["backup"], "on": ["timeout"], "max_attempts": 2, "timeout_ms": 1000}
    first = policy(action).model_copy(update={"priority": 10})
    later = policy({**action, "on": ["rate_limited"]}).model_copy(update={"priority": 20})
    key, snap = snapshot([later, first])
    plan = plan_routes(request(), key, snap)
    assert isinstance(plan, RoutePlan)
    assert plan.retry_on == ("timeout",)
    assert plan.backups == ()


@pytest.mark.parametrize("invalid", ["duplicate", "over_limit", "condition"])
def test_invalid_policies_rejected_before_bundle_admission(invalid):
    entry = policy({"kind": "byok"})
    if invalid == "duplicate":
        entries = [entry, entry]
    elif invalid == "over_limit":
        entries = [entry.model_copy(update={"id": uuid7()}) for _ in range(101)]
    else:
        entries = [policy({"kind": "byok"}, condition="unknown")]
    with pytest.raises(
        ValueError, match={"duplicate": "Duplicate policy", "over_limit": "at most 100", "condition": "Invalid policy condition"}[invalid]
    ):
        snapshot(entries)


@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("restricted", [False, True])
@respx.mock
def test_fallback_respects_restrictions_and_accounts_each_attempt(dp_app, tmp_path, http_client, stream, restricted):
    api_key, key = make_key()
    backup = MODEL.model_copy(update={"model_id": "backup", "upstream_model": "backup-upstream"})
    policies = [policy({"kind": "fallback", "models": ["backup"], "on": ["upstream_unavailable"], "max_attempts": 2, "timeout_ms": 1000})]
    if restricted:
        policies.append(policy({"kind": "models", "names": [MODEL.model_id]}, condition=f'request_model == "{MODEL.model_id}"'))
    bundle = make_bundle(keys=[key], catalog=Catalog(providers=[PROVIDER], models=[MODEL, backup], credentials=[PLATFORM_CREDENTIAL]))
    write_cached_bundles(tmp_path, CachedBundles(bundles=[bundle.model_copy(update={"policies": tuple(policies)})]))

    def upstream(incoming):
        model = json.loads(incoming.content)["model"]
        if model == MODEL.upstream_model:
            return httpx.Response(503, json={"error": {"message": "unavailable"}})
        return httpx.Response(200, content=TEXT_LOG) if stream else httpx.Response(200, json=TEXT_NONSTREAM)

    respx.post("https://api.openai.com/v1/chat/completions").mock(side_effect=upstream)
    mock_control_plane()
    with TestClient(dp_app) as client:
        result = client.post(
            "/inf/v1/chat/completions", headers={"Authorization": f"Bearer {api_key}"}, json={**request().model_dump(mode="json"), "stream": stream}
        )
    assert result.status_code == (503 if restricted else 200)
    outbox = make_outbox(tmp_path, http_client)
    events = outbox.next_batch(10)
    outbox.close()
    assert [(event.model_id, event.status) for event in events] == (
        [(MODEL.model_id, "upstream_error")] if restricted else [(MODEL.model_id, "upstream_error"), ("backup", "ok")]
    )


@pytest.mark.parametrize("failure", ["read_error", "timeout", "attempt_limit", "unmatched_reason", "midstream", "deadline"])
@respx.mock
def test_fallback_failure_boundaries(dp_app, tmp_path, http_client, failure):
    api_key, key = make_key()
    backups = [MODEL.model_copy(update={"model_id": name, "upstream_model": name}) for name in ["backup", "last"]]
    entry = policy(
        {"kind": "fallback", "models": ["backup", "last"], "on": ["upstream_unavailable", "timeout"], "max_attempts": 2, "timeout_ms": 100}
    )
    bundle = make_bundle(keys=[key], catalog=Catalog(providers=[PROVIDER], models=[MODEL, *backups], credentials=[PLATFORM_CREDENTIAL]))
    write_cached_bundles(tmp_path, CachedBundles(bundles=[bundle.model_copy(update={"policies": (entry,)})]))

    async def upstream(incoming):
        if failure == "attempt_limit":
            return httpx.Response(503, json={"error": {"message": "unavailable"}})
        if json.loads(incoming.content)["model"] != MODEL.upstream_model:
            return httpx.Response(200, json=TEXT_NONSTREAM)
        if failure == "read_error":
            message = "connection reset"
            raise httpx.ReadError(message, request=incoming)
        if failure == "timeout":
            message = "timed out"
            raise httpx.ReadTimeout(message, request=incoming)
        if failure == "midstream":
            return httpx.Response(200, content=TEXT_LOG.removesuffix(b"data: [DONE]\n\n"))
        if failure == "deadline":
            await asyncio.sleep(1)
        return httpx.Response(429, json={"error": {"message": "rate limited"}})

    respx.post("https://api.openai.com/v1/chat/completions").mock(side_effect=upstream)
    mock_control_plane()
    with TestClient(dp_app) as client:
        result = client.post(
            "/inf/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json={**request().model_dump(mode="json"), "stream": failure == "midstream"},
        )
    expected_status = {"attempt_limit": 503, "unmatched_reason": 429, "deadline": 504}.get(failure, 200)
    assert result.status_code == expected_status
    if failure == "midstream":
        assert "invalid_upstream_response" in result.text
    if failure == "deadline":
        assert "fallback_deadline_exceeded" in result.text
    outbox = make_outbox(tmp_path, http_client)
    events = outbox.next_batch(10)
    outbox.close()
    assert [event.model_id for event in events] == (
        [MODEL.model_id, "backup"] if failure in {"read_error", "timeout", "attempt_limit"} else [MODEL.model_id]
    )
    assert (
        events[-1].status
        == {
            "read_error": "ok",
            "timeout": "ok",
            "attempt_limit": "upstream_error",
            "unmatched_reason": "rate_limited",
            "midstream": "upstream_error",
            "deadline": "cancelled",
        }[failure]
    )


@respx.mock
def test_repeated_request_preserves_rate_limited_status_during_credential_cooldown(dp_app, tmp_path):
    api_key, key = make_key()
    bundle = make_bundle(keys=[key], catalog=Catalog(providers=[PROVIDER], models=[MODEL], credentials=[PLATFORM_CREDENTIAL]))
    write_cached_bundles(tmp_path, CachedBundles(bundles=[bundle]))
    respx.post("https://api.openai.com/v1/chat/completions").mock(return_value=httpx.Response(429, json={"error": {"message": "rate limited"}}))
    mock_control_plane()
    with TestClient(dp_app) as client:
        for _ in range(2):
            response = client.post("/inf/v1/chat/completions", headers={"Authorization": f"Bearer {api_key}"}, json=request().model_dump(mode="json"))
            assert response.status_code == 429
        assert "rate limited" in response.text
