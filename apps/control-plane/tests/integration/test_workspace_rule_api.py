from __future__ import annotations

from fastapi.testclient import TestClient
from helpers import make_org, make_workspace, setup_control_plane, wait_for_publication

RULE = {
    "match": {"kind": "all_requests"},
    "action": {"kind": "credential_access", "scopes": ["workspace", "org"]},
}


def test_policy_rules_are_independent(tmp_path):
    control_plane = setup_control_plane(tmp_path)
    with TestClient(control_plane.app) as client:
        org_id = make_org(client, control_plane.headers(), "inline-rules")
        headers = control_plane.headers(org_id)
        workspace_id = make_workspace(client, headers, "production")
        base = f"/api/v1/organizations/{org_id}/workspaces/{workspace_id}"

        policies = [
            client.post(
                f"{base}/policies",
                headers=headers,
                json={"name": name, "definition": {"target": {"kind": "workspace"}, "rules": [RULE]}},
            ).json()["data"]
            for name in ("First", "Second")
        ]
        replacement = {
            "target": {"kind": "workspace"},
            "rules": [{"match": {"kind": "all_requests"}, "action": {"kind": "request_limits", "max_output_tokens": 2048}}],
        }
        updated = client.patch(f"{base}/policies/{policies[0]['id']}", headers=headers, json={"definition": replacement})

        assert updated.status_code == 200, updated.text
        persisted = client.get(f"{base}/policies", headers=headers).json()["data"]
        assert persisted[0]["definition"] == replacement
        assert persisted[1]["definition"] == {"target": {"kind": "workspace"}, "rules": [RULE]}
        wait_for_publication(client, org_id, headers)
        bundle = client.get("/api/v1/bundle/latest", headers=control_plane.headers(), params={"org_id": str(org_id)}).json()["data"]
        assert len(bundle["policies"]) == 2
