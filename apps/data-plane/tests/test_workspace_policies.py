from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING

import httpx
import pytest
import respx
from conftest import (
    MODEL,
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

if TYPE_CHECKING:
    from uuid import UUID
from contract.policies import PolicyDefinition, PolicyEntry, RuleDefinition, RuleEntry
from data_plane.bundle.holder import BundleSnapshot
from data_plane.cache import CachedBundles, write_cached_bundles
from data_plane.canonical import CanonicalRequest
from data_plane.policy import Allow, Deny, evaluate, model_allowed
from data_plane.routing import RoutePlan, plan_routes


def request():
    return CanonicalRequest(model=MODEL.model_id, messages=[{"role": "user", "content": "hi"}])


RULES: dict[UUID, RuleEntry] = {}


def rule(action, *, match=None, workspace=WORKSPACE, name="test"):
    entry = RuleEntry(
        id=uuid7(),
        workspace_id=workspace,
        name=name,
        definition=RuleDefinition.model_validate({"match": match or {"kind": "all_requests"}, "action": action}),
    )
    RULES[entry.id] = entry
    return entry


def policy(action, *, match=None, workspace=WORKSPACE, target=None):
    policy_rule = rule(action, match=match, workspace=workspace)
    return PolicyEntry(
        id=uuid7(),
        workspace_id=workspace,
        name="test",
        priority=100,
        definition=PolicyDefinition.model_validate({"target": target or {"kind": "workspace"}, "rule_ids": [policy_rule.id]}),
    )


def policy_with_rules(rules, *, workspace=WORKSPACE, target=None):
    rule_entries = tuple(rule(item["action"], match=item["match"], workspace=workspace) for item in rules)
    return PolicyEntry(
        id=uuid7(),
        workspace_id=workspace,
        name="test",
        priority=100,
        definition=PolicyDefinition.model_validate({"target": target or {"kind": "workspace"}, "rule_ids": [item.id for item in rule_entries]}),
    )


def referenced_rules(policies):
    return tuple({rule_id: RULES[rule_id] for policy in policies for rule_id in policy.definition.rule_ids}.values())


def snapshot(policies, *, credentials=None, models=None, provider=PROVIDER):
    _, key = make_key()
    bundle = make_bundle(
        keys=[key],
        catalog=Catalog(providers=[provider], models=models or [MODEL], credentials=credentials or [make_credential(org=None)]),
    )
    return key, BundleSnapshot.from_bundle(bundle.model_copy(update={"rules": referenced_rules(policies), "policies": tuple(policies)}))


@pytest.mark.parametrize(
    "action",
    [
        {"kind": "credential_access", "scopes": ["workspace", "org"]},
        {"kind": "models", "names": ["other"]},
        {"kind": "providers", "names": ["other"]},
    ],
)
def test_restrictions_deny_before_upstream(action):
    key, snap = snapshot([policy(action)])
    result = evaluate(request(), key, snap)
    assert isinstance(result, Deny)
    assert result.code == "policy_denied"


@pytest.mark.parametrize(
    "options", [{"workspace": uuid7()}, {"match": {"kind": "request", "stream": True}}, {"target": {"kind": "selected_keys", "key_ids": ["other"]}}]
)
def test_only_matching_workspace_keys_and_requests_are_restricted(options):
    key, snap = snapshot([policy({"kind": "credential_access", "scopes": ["workspace", "org"]}, **options)])
    assert isinstance(evaluate(request(), key, snap), Allow)


def test_selected_key_targets_are_compiled_for_constant_time_membership():
    selected_key_ids = frozenset(str(uuid7()) for _ in range(1000))
    entry = policy(
        {"kind": "credential_access", "scopes": ["workspace", "org"]},
        target={"kind": "selected_keys", "key_ids": sorted(selected_key_ids)},
    )
    _, snap = snapshot([entry])

    assert snap.policy_index[WORKSPACE][0].selected_key_ids == selected_key_ids


def test_policy_index_preserves_workspace_evaluation_order():
    other_workspace = uuid7()
    action = {"kind": "credential_access", "scopes": ["workspace", "org"]}
    later = policy(action).model_copy(update={"priority": 20})
    first = policy(action).model_copy(update={"priority": 10})
    other = policy(action, workspace=other_workspace)

    _, snap = snapshot([later, other, first])

    assert tuple(compiled.policy.id for compiled in snap.policy_index[WORKSPACE]) == (first.id, later.id)
    assert tuple(compiled.policy.id for compiled in snap.policy_index[other_workspace]) == (other.id,)


def test_budget_does_not_enforce_yet():
    key, snap = snapshot([policy({"kind": "budget", "period": "day", "amount_usd": "1", "sharing": "shared"})])
    assert isinstance(evaluate(request(), key, snap), Allow)


def test_strict_parameters_rejects_a_parameter_the_model_would_drop():
    model = MODEL.model_copy(update={"parameter_support": {"temperature": "unsupported"}})
    key, snap = snapshot([policy({"kind": "strict_parameters"})], models=[model])

    result = evaluate(request().model_copy(update={"temperature": 0.5}), key, snap)

    assert isinstance(result, Deny)
    assert "temperature" in result.message


def test_strict_parameters_rejects_an_unknown_parameter_for_a_closed_provider():
    provider = PROVIDER.model_copy(update={"params_closed": True})
    key, snap = snapshot([policy({"kind": "strict_parameters"})], provider=provider)

    result = evaluate(CanonicalRequest.model_validate({**request().model_dump(), "unknown_option": True}), key, snap)

    assert isinstance(result, Deny)
    assert "unknown_option" in result.message


@pytest.mark.parametrize(
    ("action", "allowed"),
    [
        ({"kind": "price_limit", "max_input_price_per_mtok": "1", "max_output_price_per_mtok": "2"}, True),
        ({"kind": "price_limit", "max_input_price_per_mtok": "0.99", "max_output_price_per_mtok": "2"}, False),
        ({"kind": "price_limit", "max_input_price_per_mtok": "1", "max_output_price_per_mtok": "1.99"}, False),
    ],
)
def test_price_limit_checks_input_and_output_catalog_rates(action, allowed):
    key, snap = snapshot([policy(action)])

    assert isinstance(evaluate(request(), key, snap), Allow if allowed else Deny)


def test_request_limits_rejects_excessive_requested_output_tokens():
    key, snap = snapshot([policy({"kind": "request_limits", "max_output_tokens": 500})])

    assert isinstance(evaluate(request(), key, snap), Allow)
    assert isinstance(evaluate(request().model_copy(update={"max_tokens": 500}), key, snap), Allow)
    assert isinstance(evaluate(request().model_copy(update={"max_tokens": 501}), key, snap), Deny)


def test_credential_access_selects_the_most_specific_allowed_scope():
    workspace_credential = make_credential(name="workspace", workspace=WORKSPACE)
    org_credential = make_credential(name="org")
    platform_credential = make_credential(name="platform", org=None)
    key, snap = snapshot(
        [policy({"kind": "credential_access", "scopes": ["org", "platform"]})],
        credentials=[workspace_credential, org_credential, platform_credential],
    )

    result = evaluate(request(), key, snap)

    assert isinstance(result, Allow)
    assert result.candidates == (org_credential,)


def test_credential_access_denies_when_no_allowed_scope_has_credentials():
    key, snap = snapshot(
        [policy({"kind": "credential_access", "scopes": ["workspace"]})],
        credentials=[make_credential(name="org")],
    )

    assert isinstance(evaluate(request(), key, snap), Deny)


def test_price_limit_applies_to_fallback_models():
    backup = MODEL.model_copy(update={"model_id": "backup", "input_price_per_mtok": 5.0})
    policies = [
        policy({"kind": "fallback", "models": ["backup"], "on": ["timeout"], "max_attempts": 2, "timeout_ms": 1000}),
        policy({"kind": "price_limit", "max_input_price_per_mtok": "2", "max_output_price_per_mtok": "3"}),
    ]
    key, snap = snapshot(policies, models=[MODEL, backup])

    plan = plan_routes(request(), key, snap)

    assert isinstance(plan, RoutePlan)
    assert plan.backups == ()


def test_credential_access_policies_intersect():
    key, snap = snapshot(
        [
            policy({"kind": "credential_access", "scopes": ["workspace", "org"]}),
            policy({"kind": "credential_access", "scopes": ["platform"]}),
        ],
        credentials=[make_credential(name="org"), make_credential(name="platform", org=None)],
    )

    assert isinstance(evaluate(request(), key, snap), Deny)


def test_request_match_combines_model_stream_and_capabilities():
    match = {"kind": "request", "models": [MODEL.model_id], "stream": False, "capabilities": ["tools"]}
    key, snap = snapshot([policy({"kind": "models", "names": ["other"]}, match=match)])

    assert isinstance(evaluate(request(), key, snap), Allow)
    assert isinstance(evaluate(request().model_copy(update={"tools": [{"name": "lookup", "input_schema": {"type": "object"}}]}), key, snap), Deny)


def test_restrictions_intersect_regardless_of_priority():
    key, snap = snapshot([policy({"kind": "models", "names": [MODEL.model_id]}), policy({"kind": "models", "names": ["other"]})])
    assert isinstance(evaluate(request(), key, snap), Deny)


def test_rules_in_one_policy_compose_for_the_targeted_keys():
    entry = policy_with_rules(
        [
            {"match": {"kind": "all_requests"}, "action": {"kind": "models", "names": [MODEL.model_id]}},
            {"match": {"kind": "all_requests"}, "action": {"kind": "request_limits", "max_output_tokens": 500}},
        ]
    )
    key, snap = snapshot([entry])

    assert isinstance(evaluate(request(), key, snap), Allow)
    assert isinstance(evaluate(request().model_copy(update={"max_tokens": 501}), key, snap), Deny)


def test_one_rule_is_shared_by_multiple_policy_targets():
    shared = rule({"kind": "request_limits", "max_output_tokens": 500}, name="Shared output limit")
    first = PolicyEntry(
        id=uuid7(),
        workspace_id=WORKSPACE,
        name="All traffic",
        priority=10,
        definition=PolicyDefinition(target={"kind": "workspace"}, rule_ids=(shared.id,)),
    )
    second = PolicyEntry(
        id=uuid7(),
        workspace_id=WORKSPACE,
        name="Selected traffic",
        priority=20,
        definition=PolicyDefinition(target={"kind": "selected_keys", "key_ids": ["k-dev"]}, rule_ids=(shared.id,)),
    )

    _, snap = snapshot([first, second])

    assert tuple(compiled.rule.id for compiled in snap.policy_index[WORKSPACE]) == (shared.id, shared.id)


def test_each_rule_matches_the_original_request_independently():
    entry = policy_with_rules(
        [
            {"match": {"kind": "request", "stream": True}, "action": {"kind": "models", "names": ["other"]}},
            {"match": {"kind": "all_requests"}, "action": {"kind": "request_limits", "max_output_tokens": 500}},
        ]
    )
    key, snap = snapshot([entry])

    assert isinstance(evaluate(request(), key, snap), Allow)
    assert isinstance(evaluate(request().model_copy(update={"max_tokens": 501}), key, snap), Deny)


def test_fallback_priority_is_deterministic_and_unknown_backups_are_skipped():
    action = {"kind": "fallback", "models": ["backup"], "on": ["timeout"], "max_attempts": 2, "timeout_ms": 1000}
    first = policy(action).model_copy(update={"priority": 10})
    later = policy({**action, "on": ["rate_limited"]}).model_copy(update={"priority": 20})
    key, snap = snapshot([later, first])
    plan = plan_routes(request(), key, snap)
    assert isinstance(plan, RoutePlan)
    assert plan.retry_on == ("timeout",)
    assert plan.backups == ()


def test_one_policy_cannot_contain_multiple_fallback_rules():
    entry = policy_with_rules(
        [
            {
                "match": {"kind": "all_requests"},
                "action": {"kind": "fallback", "models": ["backup"], "on": ["timeout"], "max_attempts": 2, "timeout_ms": 1000},
            },
            {
                "match": {"kind": "all_requests"},
                "action": {"kind": "fallback", "models": ["last"], "on": ["rate_limited"], "max_attempts": 2, "timeout_ms": 1000},
            },
        ]
    )

    with pytest.raises(ValueError, match="at most one fallback rule"):
        snapshot([entry])


@pytest.mark.parametrize("invalid", ["duplicate", "over_limit"])
def test_invalid_policies_rejected_before_bundle_admission(invalid):
    entry = policy({"kind": "credential_access", "scopes": ["workspace", "org"]})
    if invalid == "duplicate":
        entries = [entry, entry]
    elif invalid == "over_limit":
        entries = [entry.model_copy(update={"id": uuid7()}) for _ in range(101)]
    with pytest.raises(ValueError, match={"duplicate": "Duplicate policy", "over_limit": "at most 100"}[invalid]):
        snapshot(entries)


@pytest.mark.parametrize("invalid", ["missing", "wrong_workspace", "duplicate"])
def test_invalid_rule_references_are_rejected_before_bundle_admission(invalid):
    entry = policy({"kind": "credential_access", "scopes": ["workspace", "org"]})
    policy_rule = RULES[entry.definition.rule_ids[0]]
    if invalid == "missing":
        rules = ()
    elif invalid == "wrong_workspace":
        rules = (policy_rule.model_copy(update={"workspace_id": uuid7()}),)
    else:
        rules = (policy_rule, policy_rule)
    _, key = make_key()
    bundle = make_bundle(keys=[key], catalog=Catalog(providers=[PROVIDER], models=[MODEL], credentials=[make_credential(org=None)]))

    with pytest.raises(ValueError, match={"missing": "unknown rule", "wrong_workspace": "another workspace", "duplicate": "Duplicate rule"}[invalid]):
        BundleSnapshot.from_bundle(bundle.model_copy(update={"rules": rules, "policies": (entry,)}))


@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize(
    "restriction", [(restricted, target) for restricted in (False, True) for target in ("workspace", "selected_users", "selected_keys")]
)
@respx.mock
def test_fallback_respects_restrictions_and_accounts_each_attempt(dp_app, tmp_path, http_client, stream, restriction):
    restricted, target_kind = restriction
    api_key, key = make_key()
    backup = MODEL.model_copy(update={"model_id": "backup", "upstream_model": "backup-upstream"})
    policies = [policy({"kind": "fallback", "models": ["backup"], "on": ["upstream_unavailable"], "max_attempts": 2, "timeout_ms": 1000})]
    target = (
        {"kind": "workspace"}
        if target_kind == "workspace"
        else {"kind": "selected_users", "user_ids": [key.user_id]}
        if target_kind == "selected_users"
        else {"kind": "selected_keys", "key_ids": [key.key_id]}
    )
    if restricted:
        policies.append(policy({"kind": "models", "names": [MODEL.model_id]}, match={"kind": "request", "models": [MODEL.model_id]}, target=target))
    bundle = make_bundle(keys=[key], catalog=Catalog(providers=[PROVIDER], models=[MODEL, backup], credentials=[PLATFORM_CREDENTIAL]))
    write_cached_bundles(
        tmp_path,
        CachedBundles(bundles=[bundle.model_copy(update={"rules": referenced_rules(policies), "policies": tuple(policies)})]),
    )

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
    write_cached_bundles(tmp_path, CachedBundles(bundles=[bundle.model_copy(update={"rules": referenced_rules((entry,)), "policies": (entry,)})]))

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
        assert response.json()["error"] == {"code": "429", "message": "rate limited"}


@pytest.mark.parametrize("stream", [False, True])
def test_user_targets_cover_all_principal_credentials_and_compose_with_workspace_and_key_limits(stream):
    _, key = make_key()
    entries = [
        policy({"kind": "request_limits", "max_output_tokens": 4096}, target={"kind": "workspace"}),
        policy({"kind": "request_limits", "max_output_tokens": 1024}, target={"kind": "selected_users", "user_ids": [key.user_id]}),
        policy({"kind": "request_limits", "max_output_tokens": 512}, target={"kind": "selected_keys", "key_ids": [key.key_id]}),
    ]
    _, snap = snapshot(entries)
    incoming = request().model_copy(update={"stream": stream, "max_tokens": 513})
    assert isinstance(evaluate(incoming, key, snap), Deny)
    assert isinstance(evaluate(incoming.model_copy(update={"max_tokens": 512}), key, snap), Allow)
    for credential_id in ("second-key", "playground-session"):
        credential = key.model_copy(update={"key_id": credential_id})
        assert isinstance(evaluate(incoming.model_copy(update={"max_tokens": 1025}), credential, snap), Deny)
        assert isinstance(evaluate(incoming, credential, snap), Allow)
    other = key.model_copy(update={"key_id": "other", "user_id": uuid7()})
    assert isinstance(evaluate(incoming.model_copy(update={"max_tokens": 1025}), other, snap), Allow)
    assert isinstance(evaluate(incoming.model_copy(update={"max_tokens": 4097}), other, snap), Deny)
    sibling = key.model_copy(update={"workspace_id": uuid7()})
    assert isinstance(evaluate(incoming.model_copy(update={"max_tokens": 4097}), sibling, snap), Allow)


def test_user_targets_share_discovery_and_enforcement_matching():
    _, key = make_key()
    entry = policy({"kind": "deny", "message": "Restricted user"}, target={"kind": "selected_users", "user_ids": [key.user_id]})
    _, snap = snapshot([entry])
    assert snap.policy_index[WORKSPACE][0].selected_user_ids == frozenset({key.user_id})
    for credential_id in (key.key_id, "second-key", "playground-session"):
        credential = key.model_copy(update={"key_id": credential_id})
        assert not model_allowed(MODEL, credential, snap)
        assert isinstance(evaluate(request(), credential, snap), Deny)
    other = key.model_copy(update={"user_id": uuid7()})
    assert model_allowed(MODEL, other, snap)
    assert isinstance(evaluate(request(), other, snap), Allow)
