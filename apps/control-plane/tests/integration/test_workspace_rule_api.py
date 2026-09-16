from __future__ import annotations

from fastapi.testclient import TestClient
from helpers import make_org, make_workspace, setup_control_plane

from contract import BundleV1

RULE = {
    "name": "Team credentials",
    "definition": {
        "match": {"kind": "all_requests"},
        "action": {"kind": "credential_access", "scopes": ["workspace", "org"]},
    },
}

BUDGET_RULE = {
    "name": "Budget",
    "definition": {
        "match": {"kind": "all_requests"},
        "action": {"kind": "budget", "period": "month", "amount_usd": "10", "sharing": "shared"},
    },
}


def test_budget_rules_are_rejected_on_create_and_update(tmp_path):
    control_plane = setup_control_plane(tmp_path)
    with TestClient(control_plane.app) as client:
        org_id = make_org(client, control_plane.headers(), "no-budget-rules")
        headers = control_plane.headers(org_id)
        workspace_id = make_workspace(client, headers, "production")
        base = f"/api/v1/organizations/{org_id}/workspaces/{workspace_id}/rules"
        rule = client.post(base, headers=headers, json=RULE).json()["data"]

        assert client.post(base, headers=headers, json=BUDGET_RULE).status_code == 422
        assert client.patch(f"{base}/{rule['id']}", headers=headers, json={"definition": BUDGET_RULE["definition"]}).status_code == 422


def test_rule_is_shared_live_across_policies_and_cannot_be_deleted_while_referenced(tmp_path):
    control_plane = setup_control_plane(tmp_path)
    with TestClient(control_plane.app) as client:
        org_id = make_org(client, control_plane.headers(), "shared-rules")
        headers = control_plane.headers(org_id)
        workspace_id = make_workspace(client, headers, "production")
        base = f"/api/v1/organizations/{org_id}/workspaces/{workspace_id}"

        created_rule = client.post(f"{base}/rules", headers=headers, json=RULE)
        assert created_rule.status_code == 200, created_rule.text
        rule = created_rule.json()["data"]

        for name, selected in (("All traffic", False), ("Customer traffic", True)):
            target: dict[str, object] = {"kind": "workspace"}
            if selected:
                key = client.post(f"{base}/inference-keys", headers=headers, json={"label": "customer"}).json()["data"]
                target = {"kind": "selected_keys", "key_ids": [key["id"]]}
            body = {"name": name, "definition": {"target": target, "rule_ids": [rule["id"]]}}
            response = client.post(f"{base}/policies", headers=headers, json=body)
            assert response.status_code == 200, response.text

        policies = client.get(f"{base}/policies", headers=headers).json()["data"]
        assert [policy["definition"]["rule_ids"] for policy in policies] == [[rule["id"]], [rule["id"]]]
        assert client.delete(f"{base}/rules/{rule['id']}", headers=headers).status_code == 409

        updated = client.patch(
            f"{base}/rules/{rule['id']}",
            headers=headers,
            json={"definition": {"match": {"kind": "all_requests"}, "action": {"kind": "request_limits", "max_output_tokens": 2048}}},
        )
        assert updated.status_code == 200, updated.text
        bundle = BundleV1.model_validate(
            client.get("/api/v1/bundle/latest", headers=control_plane.headers(), params={"org_id": str(org_id)}).json()["data"]
        )
        assert len(bundle.rules) == 1
        assert str(bundle.rules[0].id) == rule["id"]
        assert bundle.rules[0].definition.action.kind == "request_limits"


def test_policy_rejects_rule_from_another_workspace(tmp_path):
    control_plane = setup_control_plane(tmp_path)
    with TestClient(control_plane.app) as client:
        org_id = make_org(client, control_plane.headers(), "rule-isolation")
        headers = control_plane.headers(org_id)
        first = make_workspace(client, headers, "first")
        second = make_workspace(client, headers, "second")
        rule = client.post(f"/api/v1/organizations/{org_id}/workspaces/{first}/rules", headers=headers, json=RULE).json()["data"]

        response = client.post(
            f"/api/v1/organizations/{org_id}/workspaces/{second}/policies",
            headers=headers,
            json={"name": "Invalid", "definition": {"target": {"kind": "workspace"}, "rule_ids": [rule["id"]]}},
        )

        assert response.status_code == 422
