from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from helpers import make_org, make_workspace, setup_control_plane

from contract import BundleV1
from control_plane.authz import Permission

RULE_DEFINITIONS = (
    {"match": {"kind": "all_requests"}, "action": {"kind": "credential_access", "scopes": ["workspace", "org"]}},
    {"match": {"kind": "all_requests"}, "action": {"kind": "request_limits", "max_output_tokens": 4096}},
)


def create_rules(client, base, headers):
    return [
        client.post(f"{base}/rules", headers=headers, json={"name": f"Rule {index}", "definition": definition}).json()["data"]
        for index, definition in enumerate(RULE_DEFINITIONS, start=1)
    ]


def policy_definition(rules, target=None):
    return {"target": target or {"kind": "all_keys"}, "rule_ids": [rule["id"] for rule in rules]}


def test_workspace_policy_crud_validation_and_isolation(tmp_path):
    cp = setup_control_plane(tmp_path)
    with TestClient(cp.app) as client:
        org = make_org(client, cp.headers(), "policies")
        headers = cp.headers(org)
        workspace = make_workspace(client, headers, "production")
        sibling = make_workspace(client, headers, "staging")
        base = f"/api/v1/orgs/{org}/workspaces/{workspace}"
        path = f"{base}/policies"
        rules = create_rules(client, base, headers)
        body = {
            "name": "Team credentials only",
            "enabled": True,
            "priority": 100,
            "definition": policy_definition(rules),
        }
        created = client.post(path, headers=headers, json=body)
        assert created.status_code == 200, created.text
        policy = created.json()["data"]
        assert policy["workspace_id"] == str(workspace)
        assert policy["definition"]["rule_ids"] == [rule["id"] for rule in rules]
        assert [item["id"] for item in client.get(path, headers=headers).json()["data"]] == [policy["id"]]
        sibling_path = f"/api/v1/orgs/{org}/workspaces/{sibling}/policies/{policy['id']}"
        assert client.patch(sibling_path, headers=headers, json={"enabled": False}).status_code == 404
        invalid = {
            **body,
            "definition": {
                **body["definition"],
                "rule_ids": [],
            },
        }
        assert client.post(path, headers=headers, json=invalid).status_code == 422
        assert client.patch(f"{path}/{policy['id']}", headers=headers, json={"name": None}).status_code == 422
        assert client.patch(f"{path}/{policy['id']}", headers=headers, json={"enabled": False}).json()["data"]["enabled"] is False
        assert client.delete(f"{path}/{policy['id']}", headers=headers).status_code == 200
        assert client.get(path, headers=headers).json()["data"] == []


@pytest.mark.parametrize("role", ["admin", "member", "viewer"])
def test_workspace_policy_permissions(tmp_path, role):
    cp = setup_control_plane(tmp_path)
    with TestClient(cp.app, base_url="https://testserver") as client:
        org = make_org(client, cp.headers(), "policies")
        headers = cp.headers(org)
        workspace = make_workspace(client, headers, "production")
        base = f"/api/v1/orgs/{org}/workspaces/{workspace}"
        rules = create_rules(client, base, headers)
        member = client.post("/api/v1/auth/signup", json={"email": "member@example.com", "name": "Member", "password": "hunter2-hunter2"}).json()[
            "data"
        ]
        assert client.put(f"/api/v1/orgs/{org}/users/{member['user_id']}", headers=headers, json={"role": "member"}).status_code == 200
        assert (
            client.put(f"/api/v1/orgs/{org}/workspaces/{workspace}/members/{member['user_id']}", headers=headers, json={"role": role}).status_code
            == 200
        )
        path = f"{base}/policies"
        definition = policy_definition(rules)
        created = client.post(path, headers=headers, json={"name": "Team credentials", "definition": definition}).json()["data"]
        session_headers = {"X-Requested-With": "fetch"}
        assert client.get(path, headers=session_headers).status_code == 200
        expected = 200 if role == "admin" else 403
        assert client.post(path, headers=session_headers, json={"name": "Second", "definition": definition}).status_code == expected
        policy_ids = [policy["id"] for policy in client.get(path, headers=session_headers).json()["data"]]
        assert client.put(f"{path}/order", headers=session_headers, json={"policy_ids": policy_ids}).status_code == expected
        assert client.patch(f"{path}/{created['id']}", headers=session_headers, json={"enabled": False}).status_code == expected
        assert client.delete(f"{path}/{created['id']}", headers=session_headers).status_code == expected


def test_workspace_policy_order_is_replaced_atomically(tmp_path):
    cp = setup_control_plane(tmp_path)
    with TestClient(cp.app) as client:
        org = make_org(client, cp.headers(), "policies")
        headers = cp.headers(org)
        workspace = make_workspace(client, headers, "production")
        base = f"/api/v1/orgs/{org}/workspaces/{workspace}"
        path = f"{base}/policies"
        definition = policy_definition(create_rules(client, base, headers))
        policies = [
            client.post(path, headers=headers, json={"name": name, "priority": priority, "definition": definition}).json()["data"]
            for name, priority in (("First", 10), ("Second", 20), ("Third", 30))
        ]
        ordered_ids = [policy["id"] for policy in reversed(policies)]
        bundles_before = client.get(f"/api/v1/orgs/{org}/bundles", headers=headers).json()["data"]

        reordered = client.put(f"{path}/order", headers=headers, json={"policy_ids": ordered_ids})

        assert reordered.status_code == 200, reordered.text
        assert [policy["id"] for policy in reordered.json()["data"]] == ordered_ids
        assert [policy["priority"] for policy in reordered.json()["data"]] == [0, 1, 2]
        assert [policy["id"] for policy in client.get(path, headers=headers).json()["data"]] == ordered_ids
        bundle = BundleV1.model_validate(client.get("/api/v1/bundle/latest", headers=cp.headers(), params={"org_id": str(org)}).json()["data"])
        assert {str(policy.id): policy.priority for policy in bundle.policies} == dict(zip(ordered_ids, range(3), strict=True))
        assert len(client.get(f"/api/v1/orgs/{org}/bundles", headers=headers).json()["data"]) == len(bundles_before) + 1

        incomplete = client.put(f"{path}/order", headers=headers, json={"policy_ids": ordered_ids[:-1]})
        assert incomplete.status_code == 422
        duplicate = client.put(f"{path}/order", headers=headers, json={"policy_ids": [ordered_ids[0], ordered_ids[0], ordered_ids[2]]})
        assert duplicate.status_code == 422
        assert [policy["id"] for policy in client.get(path, headers=headers).json()["data"]] == ordered_ids


def test_policy_rejects_cross_workspace_keys_unknown_catalog_and_unprivileged_writes(tmp_path):
    cp = setup_control_plane(tmp_path)
    with TestClient(cp.app) as client:
        org = make_org(client, cp.headers(), "policies")
        headers = cp.headers(org)
        workspace = make_workspace(client, headers, "production")
        sibling = make_workspace(client, headers, "sibling")
        caller = client.post(f"/api/v1/orgs/{org}/workspaces/{sibling}/inference-keys", headers=headers, json={"label": "sibling"}).json()["data"]
        base = f"/api/v1/orgs/{org}/workspaces/{workspace}"
        path = f"{base}/policies"
        rules = create_rules(client, base, headers)
        definition = policy_definition(rules)
        definitions = [
            {**definition, "target": {"kind": "selected_keys", "key_ids": [caller["id"]]}},
            {**definition, "rule_ids": [str(workspace)]},
        ]
        for definition in definitions:
            response = client.post(path, headers=headers, json={"name": "Invalid", "definition": definition})
            assert response.status_code == 422, response.text
        reader = cp.headers(org, permissions=[Permission.policies_read])
        assert client.get(path, headers=reader).status_code == 200
        assert client.post(path, headers=reader, json={"name": "Forbidden", "definition": definition}).status_code == 403
