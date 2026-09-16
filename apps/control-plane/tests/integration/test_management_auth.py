from __future__ import annotations

from fastapi.testclient import TestClient
from helpers import MODEL, PROVIDER, inference_key_body, make_org, make_workspace, setup_control_plane

from contract import BundleV1, uuid7


def test_cross_org_key_revocation_is_not_found(tmp_path):
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    with TestClient(cp.app) as c:
        o1 = make_org(c, root, "o1")
        o2 = make_org(c, root, "o2")
        ws = make_workspace(c, cp.headers(o1))
        headers = cp.headers(o1)
        key = c.post(f"/api/v1/organizations/{o1}/workspaces/{ws}/inference-keys", json=inference_key_body(c, headers, "k"), headers=headers).json()[
            "data"
        ]
        assert c.delete(f"/api/v1/organizations/{o2}/workspaces/{ws}/inference-keys/{key['id']}", headers=cp.headers(o2)).status_code == 404
        c.post(f"/api/v1/organizations/{o1}/bundles/republish", headers=cp.headers(o1))
        bundle = BundleV1.model_validate(c.get("/api/v1/bundle/latest", params={"org_id": str(o1)}, headers=root).json()["data"])
        assert [k.key_id for k in bundle.keys] == [key["id"]]


def test_auth_required_everywhere(tmp_path):
    cp = setup_control_plane(tmp_path)
    with TestClient(cp.app) as c:
        assert c.post("/api/v1/organizations", json={"name": "o1"}).status_code == 401
        assert c.get(f"/api/v1/organizations/{uuid7()}/workspaces").status_code == 401
        assert c.get("/api/v1/instance/taxonomy").status_code == 401
        assert c.post("/api/v1/organizations", json={"name": "o1"}, headers={"authorization": "Bearer garbage"}).status_code == 401
        assert c.get("/api/v1/bundle/latest").status_code == 401
        assert c.get("/api/v1/bundle/latest", headers={"authorization": "Bearer garbage"}).status_code == 401


def test_org_scoped_keys_cannot_use_instance_permissions(tmp_path):
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    with TestClient(cp.app) as c:
        org_id = make_org(c, root, "o1")
        org = cp.headers(org_id)

        assert c.post("/api/v1/organizations", json={"name": "o2"}, headers=org).status_code == 403
        assert c.get("/api/v1/organizations", headers=org).status_code == 403
        assert c.post("/api/v1/instance/taxonomy/providers", json=PROVIDER, headers=org).status_code == 403
        assert c.post("/api/v1/instance/taxonomy/models", json=MODEL, headers=org).status_code == 403
        assert c.get(f"/api/v1/organizations/{org_id}/taxonomy", headers=org).status_code == 200
        assert c.get("/api/v1/instance/taxonomy", headers=root).status_code == 200

        assert c.post(f"/api/v1/organizations/{org_id}/bundles/republish", headers=root).status_code == 200
        for path in (
            f"/api/v1/organizations/{org_id}/workspaces",
            f"/api/v1/organizations/{org_id}/bundles",
            f"/api/v1/organizations/{org_id}/events",
        ):
            assert c.get(path, headers=root).status_code == 200


def test_inference_token_is_rejected_on_management_routes(tmp_path):
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    with TestClient(cp.app) as c:
        org_id = make_org(c, root, "o1")
        org = cp.headers(org_id)
        ws = make_workspace(c, org)
        key = c.post(f"/api/v1/organizations/{org_id}/workspaces/{ws}/inference-keys", json=inference_key_body(c, org, "k"), headers=org).json()[
            "data"
        ]
        inference = {"authorization": f"Bearer {key['token']}"}
        assert c.get("/api/v1/organizations", headers=inference).status_code == 401
        assert c.get(f"/api/v1/organizations/{org_id}/workspaces", headers=inference).status_code == 401


def test_orgs_cannot_reach_each_other(tmp_path):
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    with TestClient(cp.app) as c:
        o1_id = make_org(c, root, "o1")
        o2_id = make_org(c, root, "o2")
        o1 = cp.headers(o1_id)
        o2 = cp.headers(o2_id)
        c.post("/api/v1/instance/taxonomy/providers", json=PROVIDER, headers=root)
        ws = make_workspace(c, o1)
        key = c.post(f"/api/v1/organizations/{o1_id}/workspaces/{ws}/inference-keys", json=inference_key_body(c, o1, "k"), headers=o1).json()["data"]

        assert c.delete(f"/api/v1/organizations/{o2_id}/workspaces/{ws}/inference-keys/{key['id']}", headers=o2).status_code == 404
        assert c.get(f"/api/v1/organizations/{o2_id}/workspaces", headers=o2).json()["data"] == []
        taxonomy = c.get(f"/api/v1/organizations/{o2_id}/taxonomy", headers=o2).json()["data"]
        assert [p["name"] for p in taxonomy["providers"]] == ["openai"]
        assert taxonomy == c.get(f"/api/v1/organizations/{o1_id}/taxonomy", headers=o1).json()["data"]
