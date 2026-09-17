from __future__ import annotations

from uuid import UUID

from fastapi.testclient import TestClient
from helpers import MODEL, PROVIDER, inference_key_body, make_org, make_workspace, setup_control_plane


def test_list_endpoints_read_back(tmp_path):
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    with TestClient(cp.app) as c:
        org_id = make_org(c, root, "o1")
        org = cp.headers(org_id)
        ws = make_workspace(c, org)
        key = c.post(f"/api/v1/organizations/{org_id}/workspaces/{ws}/inference-keys", json=inference_key_body(c, org, "k"), headers=org).json()[
            "data"
        ]
        c.post("/api/v1/instance/taxonomy/providers", json=PROVIDER, headers=root)
        c.post("/api/v1/instance/taxonomy/models", json=MODEL, headers=root)

        assert [o["name"] for o in c.get("/api/v1/organizations", headers=root).json()["data"]] == ["o1"]
        keys = c.get(f"/api/v1/organizations/{org_id}/workspaces/{ws}/inference-keys", headers=org).json()["data"]
        assert [k["id"] for k in keys] == [key["id"]]
        assert keys[0]["workspace_id"] == str(ws)
        assert "token" not in keys[0]
        assert "token_hash" not in keys[0]
        assert UUID(keys[0]["user_id"]).version == 7
        taxonomy = c.get(f"/api/v1/organizations/{org_id}/taxonomy", headers=org).json()["data"]
        assert [p["name"] for p in taxonomy["providers"]] == ["openai"]
        assert [m["name"] for m in taxonomy["models"]] == ["gpt-test"]
