"""Every key listing carries the head of its token, so a key can be told apart from its siblings."""

from __future__ import annotations

from fastapi.testclient import TestClient
from helpers import make_org, make_workspace, setup_control_plane


def _one(response):
    assert response.status_code == 200, response.text
    return response.json()["data"]


def test_inference_key_listing_carries_the_token_head(tmp_path):
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    with TestClient(cp.app) as c:
        org = make_org(c, root, "o1")
        headers = cp.headers(org)
        workspace = make_workspace(c, headers, "staging")

        minted = _one(c.post(f"/v1/org/workspaces/{workspace}/inference-keys", json={"label": "k"}, headers=headers))
        listed = _one(c.get(f"/v1/org/workspaces/{workspace}/inference-keys", headers=headers))[0]

        assert minted["token"].startswith(listed["prefix"])
        assert listed["prefix"] != minted["token"]
        assert len(listed["prefix"]) < len(minted["token"])


def test_management_key_listing_carries_the_token_head(tmp_path):
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    with TestClient(cp.app) as c:
        org = make_org(c, root, "o1")
        headers = cp.headers(org)

        minted = _one(c.post("/v1/org/management-keys", json={"label": "ci"}, headers=headers))
        listed = next(k for k in _one(c.get("/v1/org/management-keys", headers=headers)) if k["id"] == minted["id"])

        assert minted["token"].startswith(listed["prefix"])
        assert listed["prefix"].startswith("sk-mgmt-")


def test_instance_key_listing_carries_the_token_head(tmp_path):
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    with TestClient(cp.app) as c:
        minted = _one(c.post("/v1/instance/instance-keys", json={"label": "admin"}, headers=root))
        listed = next(k for k in _one(c.get("/v1/instance/instance-keys", headers=root)) if k["id"] == minted["id"])

        assert minted["token"].startswith(listed["prefix"])
        assert listed["prefix"].startswith("sk-inst-")


def test_two_keys_of_a_kind_are_told_apart_by_their_prefix(tmp_path):
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    with TestClient(cp.app) as c:
        org = make_org(c, root, "o1")
        headers = cp.headers(org)

        first = _one(c.post("/v1/org/management-keys", json={"label": "same"}, headers=headers))
        second = _one(c.post("/v1/org/management-keys", json={"label": "same"}, headers=headers))
        listed = {k["id"]: k["prefix"] for k in _one(c.get("/v1/org/management-keys", headers=headers))}

        assert listed[first["id"]] != listed[second["id"]]
