from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

from fastapi.testclient import TestClient
from helpers import MODEL, PROVIDER, inference_key_body, make_org, make_workspace, setup_control_plane

from contract.budgets import budget_window
from control_plane.authz import Permission

from .test_events import _event


def budget_rule(amount="100", period="month", sharing="shared", match=None):
    return {"match": match or {"kind": "all_requests"}, "action": {"kind": "budget", "amount_usd": amount, "period": period, "sharing": sharing}}


def test_new_recreated_and_overlapping_budgets_count_history(tmp_path):
    cp = setup_control_plane(tmp_path)
    with TestClient(cp.app) as client:
        org = make_org(client, cp.headers(), "budgets")
        headers = cp.headers(org)
        workspace = make_workspace(client, headers, "production")
        path = f"/api/v1/organizations/{org}/workspaces/{workspace}/policies"
        event = {**_event(org), "workspace_id": str(workspace), "cost_usd": "70", "cost_input_usd": "70"}
        assert client.post("/api/v1/events", headers=headers, json=[event, event]).status_code == 200
        body = {"name": "Spending", "definition": {"target": {"kind": "workspace"}, "rules": [budget_rule(), budget_rule("50", "day")]}}
        for _ in range(2):
            created = client.post(path, headers=headers, json=body)
            assert created.status_code == 200, created.text
            policy = created.json()["data"]
            response = client.get(f"{path}/{policy['id']}/status", headers=headers)
            assert response.status_code == 200, response.text
            budgets = response.json()["data"]["budgets"]
            assert len(budgets) == 2
            assert {Decimal(budget["spent_usd"]) for budget in budgets} == {Decimal(70)}
            assert {Decimal(budget["remaining_usd"]) for budget in budgets} == {Decimal(0), Decimal(30)}
            state = client.post("/api/v1/policy-state/sync", headers=headers, json={"org_ids": [str(org)]})
            assert state.status_code == 200, state.text
            assert {budget["exhausted"] for budget in state.json()["data"]["organizations"][0]["budgets"]} == {False, True}
            client.patch(f"{path}/{policy['id']}", headers=headers, json={"enabled": False}).raise_for_status()
            disabled = client.post("/api/v1/policy-state/sync", headers=headers, json={"org_ids": [str(org)]}).json()["data"]
            assert disabled["organizations"][0]["budgets"] == []
            updated = {"target": {"kind": "workspace"}, "rules": [budget_rule("80", "day"), budget_rule("90")]}
            client.patch(f"{path}/{policy['id']}", headers=headers, json={"enabled": True, "definition": updated}).raise_for_status()
            revised = client.get(f"{path}/{policy['id']}/status", headers=headers).json()["data"]["budgets"]
            assert all(Decimal(budget["spent_usd"]) == 70 and not budget["exhausted"] for budget in revised)
            assert client.delete(f"{path}/{policy['id']}", headers=headers).status_code == 200
        empty = client.post("/api/v1/policy-state/sync", headers=headers, json={"org_ids": [str(org)]}).json()["data"]
        assert empty["organizations"][0]["budgets"] == []


def test_filtered_history_per_key_pages_and_permissions(tmp_path):

    cp = setup_control_plane(tmp_path)
    with TestClient(cp.app) as client:
        root = cp.headers()
        client.post("/api/v1/instance/taxonomy/providers", json=PROVIDER, headers=root).raise_for_status()
        client.post("/api/v1/instance/taxonomy/models", json=MODEL, headers=root).raise_for_status()
        org = make_org(client, root, "filters")
        other_org = make_org(client, root, "other")
        headers = cp.headers(org)
        workspace = make_workspace(client, headers, "production")
        other_workspace = make_workspace(client, headers, "development")
        base = f"/api/v1/organizations/{org}/workspaces/{workspace}"
        key_body = inference_key_body(client, headers, "Budget key")
        client.put(f"/api/v1/organizations/{org}/users/{key_body['user_id']}", headers=headers, json={"role": "owner"}).raise_for_status()
        keys = [client.post(f"{base}/inference-keys", headers=headers, json=key_body).json()["data"]["id"] for _ in range(2)]
        start, end = budget_window("month", datetime.now(UTC))
        events = [
            {
                **_event(org),
                "workspace_id": str(workspace),
                "user_id": key_body["user_id"],
                "key_id": key,
                "requested_model_id": MODEL["model_id"],
                "model_id": "fallback-model",
                "requested_capabilities": ["tools", "reasoning"],
                "stream": True,
                "cost_usd": amount,
                "cost_input_usd": amount,
            }
            for key, amount in zip(keys, ("70", "20"), strict=True)
        ]
        excluded = [
            {**events[0], "event_id": str(uuid4()), **change}
            for change in (
                {"workspace_id": str(other_workspace)},
                {"stream": False},
                {"requested_capabilities": []},
                {"requested_model_id": "different"},
                {"occurred_at": (start - timedelta(microseconds=1)).isoformat()},
                {"occurred_at": end.isoformat()},
            )
        ]
        client.post("/api/v1/events", headers=headers, json=events + excluded).raise_for_status()
        match = {"kind": "request", "models": [MODEL["model_id"]], "stream": True, "capabilities": ["tools"]}
        created = client.post(
            f"{base}/policies",
            headers=headers,
            json={
                "name": "User spending",
                "definition": {
                    "target": {"kind": "selected_users", "user_ids": [key_body["user_id"]]},
                    "rules": [budget_rule("50", sharing="per_key", match=match)],
                },
            },
        )
        assert created.status_code == 200, created.text
        policy = created.json()["data"]
        path = f"{base}/policies/{policy['id']}/status"
        first = client.get(path, headers=headers, params={"limit": 1}).json()["data"]["budgets"][0]
        second = client.get(path, headers=headers, params={"limit": 1, "after_key": first["next_key"]}).json()["data"]["budgets"][0]
        assert {Decimal(key["spent_usd"]) for page in (first, second) for key in page["keys"]} == {Decimal(70), Decimal(20)}
        assert second["next_key"] is None
        sync = client.post("/api/v1/policy-state/sync", headers=headers, json={"org_ids": [str(org)]}).json()["data"]
        assert sync["organizations"][0]["budgets"][0]["exhausted_key_ids"] == [keys[0]]
        assert client.get(path, headers=cp.headers(org, permissions=[Permission.policies_read])).status_code == 403
        assert client.get(path, headers=cp.headers(org, permissions=[Permission.usage_read])).status_code == 403
        assert client.post("/api/v1/policy-state/sync", headers=headers, json={"org_ids": [str(other_org)]}).status_code == 403
        assert (
            client.post(
                "/api/v1/policy-state/sync", headers=cp.headers(org, permissions=[Permission.bundles_read]), json={"org_ids": [str(org)]}
            ).status_code
            == 403
        )
        for key in keys:
            client.delete(f"{base}/inference-keys/{key}", headers=headers).raise_for_status()
        after_delete = client.get(path, headers=headers).json()["data"]["budgets"][0]
        assert sum(Decimal(key["spent_usd"]) for key in after_delete["keys"]) == Decimal(90)
