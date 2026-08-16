"""Workspaces: the scope inference keys live in, membership drawn from the org."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from helpers import make_org, make_user, make_workspace, run_in_db, setup_control_plane
from sqlmodel import col

from contract import SignedBundle, uuid7, verify_bundle
from control_plane.models import AuditLog


def _member(c, cp, org_id, email, tmp_path):
    """A real org member with an org-scoped management key: the non-admin path through every dep."""
    uid = str(make_user(tmp_path, email).id)
    assert c.put(f"/v1/org/users/{uid}", headers=cp.headers(org_id)).status_code == 200
    minted = c.post("/v1/org/management-keys", json={"user_id": uid, "label": "t"}, headers=cp.headers(org_id)).json()["data"]
    return uid, {"authorization": f"Bearer {minted['token']}"}


def test_workspace_lifecycle_and_creator_auto_enrollment(tmp_path):
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    with TestClient(cp.app) as c:
        o1 = make_org(c, root, "o1")
        uid, member = _member(c, cp, o1, "m@example.com", tmp_path)
        assert c.get("/v1/org/workspaces", headers=member).json()["data"] == []

        created = c.post("/v1/org/workspaces", json={"name": "staging", "slug": "staging"}, headers=member).json()["data"]
        assert created["org_id"] == str(o1)
        assert created["name"] == "staging"
        assert created["slug"] == "staging"
        renamed = c.patch(f"/v1/org/workspaces/{created['id']}", json={"name": "prod"}, headers=member).json()["data"]
        assert renamed["name"] == "prod"
        assert [w["name"] for w in c.get("/v1/org/workspaces", headers=member).json()["data"]] == ["prod"]

        members = c.get(f"/v1/org/workspaces/{created['id']}/members", headers=member).json()["data"]
        assert [(m["user_id"], m["status"]) for m in members] == [(uid, "member")]


def test_slug_is_unique_within_the_org_and_free_across_orgs(tmp_path):
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    with TestClient(cp.app) as c:
        o1 = make_org(c, root, "o1")
        o2 = make_org(c, root, "o2")
        assert c.post("/v1/org/workspaces", json={"name": "Staging", "slug": "staging"}, headers=cp.headers(o1)).status_code == 200
        assert c.post("/v1/org/workspaces", json={"name": "Other staging", "slug": "staging"}, headers=cp.headers(o1)).status_code == 409
        assert c.post("/v1/org/workspaces", json={"name": "Staging", "slug": "staging"}, headers=cp.headers(o2)).status_code == 200


def test_slug_is_create_only(tmp_path):
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    with TestClient(cp.app) as c:
        o1 = make_org(c, root, "o1")
        org = cp.headers(o1)
        ws = make_workspace(c, org, "staging")
        assert c.patch(f"/v1/org/workspaces/{ws}", json={"name": "prod", "slug": "prod"}, headers=org).status_code == 422
        workspace = c.get(f"/v1/org/workspaces/{ws}", headers=org).json()["data"]
        assert (workspace["name"], workspace["slug"]) == ("staging", "staging")


def test_an_omitted_slug_is_derived_from_the_name(tmp_path):
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    with TestClient(cp.app) as c:
        o1 = make_org(c, root, "o1")
        org = cp.headers(o1)

        def create(name):
            return c.post("/v1/org/workspaces", json={"name": name}, headers=org).json()["data"]["slug"]

        assert create("Staging") == "staging"
        assert create("Michel's EU / Prod!") == "michel-s-eu-prod"
        assert create("Staging") == "staging-2"
        assert create("Staging") == "staging-3"
        assert create("スタッフ") == "workspace"

        assert c.get("/v1/org/workspaces/staging-2", headers=org).json()["data"]["name"] == "Staging"


def test_a_chosen_slug_is_never_silently_numbered(tmp_path):
    """Derivation resolves collisions; an explicit slug is a request that either lands or fails."""
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    with TestClient(cp.app) as c:
        o1 = make_org(c, root, "o1")
        org = cp.headers(o1)
        assert c.post("/v1/org/workspaces", json={"name": "Staging"}, headers=org).json()["data"]["slug"] == "staging"
        assert c.post("/v1/org/workspaces", json={"name": "Other", "slug": "staging"}, headers=org).status_code == 409


def test_workspace_routes_resolve_by_slug(tmp_path):
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    with TestClient(cp.app) as c:
        o1 = make_org(c, root, "o1")
        o2 = make_org(c, root, "o2")
        org = cp.headers(o1)
        ws = make_workspace(c, org, "staging")

        assert c.get("/v1/org/workspaces/staging", headers=org).json()["data"]["id"] == str(ws)
        assert c.get("/v1/org/workspaces/staging/members", headers=org).status_code == 200
        key = c.post("/v1/org/workspaces/staging/inference-keys", json={"label": "k"}, headers=org).json()["data"]
        assert [k["id"] for k in c.get(f"/v1/org/workspaces/{ws}/inference-keys", headers=org).json()["data"]] == [key["id"]]

        assert c.get("/v1/org/workspaces/staging", headers=cp.headers(o2)).status_code == 404
        assert c.get("/v1/org/workspaces/nope", headers=org).status_code == 404

        renamed = c.patch("/v1/org/workspaces/staging", json={"name": "prod"}, headers=org).json()["data"]
        assert (renamed["name"], renamed["slug"]) == ("prod", "staging")
        assert c.delete("/v1/org/workspaces/staging", headers=org).json()["data"]["id"] == str(ws)


@pytest.mark.parametrize("slug", ["Staging", "with space", "trailing-", "under_score", "0198f3c6-e1d8-7b4a-8c2d-1f4e5a6b7c8d", ""])
def test_slug_shapes_the_api_refuses(tmp_path, slug):
    """Lowercase alphanumeric words joined by single hyphens, and never uuid-shaped: a slug that
    could be read as an id would shadow the workspace whose id it is."""
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    with TestClient(cp.app) as c:
        o1 = make_org(c, root, "o1")
        assert c.post("/v1/org/workspaces", json={"name": "n", "slug": slug}, headers=cp.headers(o1)).status_code == 422


def test_workspace_routes_404_outside_the_org(tmp_path):
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    with TestClient(cp.app) as c:
        o1 = make_org(c, root, "o1")
        o2 = make_org(c, root, "o2")
        ws = make_workspace(c, cp.headers(o1))
        assert c.get(f"/v1/org/workspaces/{uuid7()}/inference-keys", headers=cp.headers(o1)).status_code == 404
        assert c.get(f"/v1/org/workspaces/{ws}/inference-keys", headers=cp.headers(o2)).status_code == 404
        assert c.patch(f"/v1/org/workspaces/{ws}", json={"name": "x"}, headers=cp.headers(o2)).status_code == 404
        assert c.get(f"/v1/org/workspaces/{ws}/members", headers=cp.headers(o2)).status_code == 404
        assert c.get("/v1/org/workspaces", headers=cp.headers(o2)).json()["data"] == []


def test_adding_a_non_org_member_is_a_conflict(tmp_path):
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    with TestClient(cp.app) as c:
        o1 = make_org(c, root, "o1")
        ws = make_workspace(c, cp.headers(o1))
        outsider = make_user(tmp_path, "out@example.com").id
        assert c.put(f"/v1/org/workspaces/{ws}/members/{outsider}", headers=cp.headers(o1)).status_code == 409
        assert c.put(f"/v1/org/workspaces/{ws}/members/{uuid7()}", headers=cp.headers(o1)).status_code == 404


def test_key_operations_require_workspace_membership(tmp_path):
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    with TestClient(cp.app) as c:
        o1 = make_org(c, root, "o1")
        _, creator = _member(c, cp, o1, "creator@example.com", tmp_path)
        _, outsider = _member(c, cp, o1, "orgmate@example.com", tmp_path)
        ws = make_workspace(c, creator)

        assert c.post(f"/v1/org/workspaces/{ws}/inference-keys", json={"label": "k"}, headers=creator).status_code == 200
        assert c.get(f"/v1/org/workspaces/{ws}/inference-keys", headers=creator).status_code == 200

        assert c.post(f"/v1/org/workspaces/{ws}/inference-keys", json={"label": "k"}, headers=outsider).status_code == 403
        assert c.get(f"/v1/org/workspaces/{ws}/inference-keys", headers=outsider).status_code == 403

        admin = cp.headers(o1)
        assert c.get(f"/v1/org/workspaces/{ws}/inference-keys", headers=admin).status_code == 200


def test_membership_lifecycle_within_the_workspace(tmp_path):
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    with TestClient(cp.app) as c:
        o1 = make_org(c, root, "o1")
        _, creator = _member(c, cp, o1, "creator@example.com", tmp_path)
        joiner, joiner_headers = _member(c, cp, o1, "joiner@example.com", tmp_path)
        ws = make_workspace(c, creator)

        assert c.get(f"/v1/org/workspaces/{ws}/inference-keys", headers=joiner_headers).status_code == 403
        assert c.put(f"/v1/org/workspaces/{ws}/members/{joiner}", headers=creator).status_code == 200
        assert c.put(f"/v1/org/workspaces/{ws}/members/{joiner}", headers=creator).status_code == 200
        assert c.get(f"/v1/org/workspaces/{ws}/inference-keys", headers=joiner_headers).status_code == 200

        deleted = c.delete(f"/v1/org/workspaces/{ws}/members/{joiner}", headers=creator).json()["data"]
        assert deleted["id"] == f"{joiner}/{ws}"
        assert c.delete(f"/v1/org/workspaces/{ws}/members/{joiner}", headers=creator).status_code == 404
        assert c.get(f"/v1/org/workspaces/{ws}/inference-keys", headers=joiner_headers).status_code == 403


def test_org_membership_removal_cascades_out_of_workspaces(tmp_path):
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    with TestClient(cp.app) as c:
        o1 = make_org(c, root, "o1")
        uid, member = _member(c, cp, o1, "m@example.com", tmp_path)
        ws = make_workspace(c, member)
        assert [m["user_id"] for m in c.get(f"/v1/org/workspaces/{ws}/members", headers=cp.headers(o1)).json()["data"]] == [uid]

        assert c.delete(f"/v1/org/users/{uid}", headers=cp.headers(o1)).status_code == 200
        assert c.get(f"/v1/org/workspaces/{ws}/members", headers=cp.headers(o1)).json()["data"] == []

        async def cascade_audit_rows():
            return await AuditLog.find(AuditLog.table_name == "workspace_membership", AuditLog.action == "delete", order_by=col(AuditLog.id))

        rows = run_in_db(tmp_path, cascade_audit_rows)
        assert [r.record_id for r in rows] == [f"{uid}/{ws}"]
        assert all(r.user_id for r in rows)


def test_bundle_spans_workspaces_and_keys_carry_their_workspace(tmp_path):
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    with TestClient(cp.app) as c:
        o1 = make_org(c, root, "o1")
        org = cp.headers(o1)
        ws1 = make_workspace(c, org, "one")
        ws2 = make_workspace(c, org, "two")
        k1 = c.post(f"/v1/org/workspaces/{ws1}/inference-keys", json={"label": "k1"}, headers=org).json()["data"]
        k2 = c.post(f"/v1/org/workspaces/{ws2}/inference-keys", json={"label": "k2"}, headers=org).json()["data"]

        c.post("/v1/org/bundles/compile", headers=org)
        bundle = verify_bundle(SignedBundle.model_validate(c.get("/v1/bundle/latest", headers=root).json()["data"]), cp.bundle_key.public_key())
        assert {(k.key_id, str(k.workspace_id)) for k in bundle.keys} == {(k1["id"], str(ws1)), (k2["id"], str(ws2))}

        assert c.delete(f"/v1/org/workspaces/{ws2}/inference-keys/{k1['id']}", headers=org).status_code == 404
        assert c.delete(f"/v1/org/workspaces/{ws1}/inference-keys/{k1['id']}", headers=org).status_code == 200
        c.post("/v1/org/bundles/compile", headers=org)
        bundle = verify_bundle(SignedBundle.model_validate(c.get("/v1/bundle/latest", headers=root).json()["data"]), cp.bundle_key.public_key())
        assert [k.key_id for k in bundle.keys] == [k2["id"]]
