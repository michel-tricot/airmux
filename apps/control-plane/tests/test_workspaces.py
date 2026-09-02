"""Workspaces: the scope inference keys live in, membership drawn from the org."""

from __future__ import annotations

from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from helpers import captured_sql, make_org, make_workspace, run_in_db, setup_control_plane
from sqlmodel import col

from contract import SignedBundle, uuid7, verify_bundle
from control_plane.authz import OrgRole
from control_plane.models import AuditLog

CSRF = {"X-Requested-With": "fetch"}


def _member(c, cp, org_id, email, role: OrgRole = OrgRole.member):
    created = c.post("/api/v1/auth/signup", json={"email": email, "name": email, "password": "hunter2-hunter2"})
    assert created.status_code == 200, created.text
    uid = created.json()["data"]["user_id"]
    assert c.put(f"/api/v1/orgs/{org_id}/users/{uid}", json={"role": role}, headers=cp.headers(org_id)).status_code == 200
    return uid, cp.headers_for(org_id, uid)


def test_org_member_only_sees_joined_workspaces(tmp_path):
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    with TestClient(cp.app, base_url="https://testserver") as c:
        org_id = make_org(c, root, "o1")
        org = cp.headers(org_id)
        joined = make_workspace(c, org, "joined")
        sibling = make_workspace(c, org, "sibling")
        member_id, _ = _member(c, cp, org_id, "member@example.com")
        assert (
            c.put(
                f"/api/v1/orgs/{org_id}/workspaces/{joined}/members/{member_id}",
                json={"role": "viewer"},
                headers=org,
            ).status_code
            == 200
        )

        with captured_sql(cp.app) as statements:
            listed = c.get(f"/api/v1/orgs/{org_id}/workspaces", headers=CSRF)

        assert listed.status_code == 200
        assert len([statement for statement in statements if statement.lstrip().startswith("SELECT")]) <= 7
        assert [workspace["id"] for workspace in listed.json()["data"]] == [str(joined)]
        assert c.get(f"/api/v1/orgs/{org_id}/workspaces/{joined}", headers=CSRF).status_code == 200
        assert c.get(f"/api/v1/orgs/{org_id}/workspaces/{sibling}", headers=CSRF).status_code == 403


def test_workspace_lifecycle_and_creator_auto_enrollment(tmp_path):
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    with TestClient(cp.app) as c:
        o1 = make_org(c, root, "o1")
        uid, member = _member(c, cp, o1, "m@example.com", OrgRole.admin)
        assert c.get(f"/api/v1/orgs/{o1}/workspaces", headers=member).json()["data"] == []

        created = c.post(f"/api/v1/orgs/{o1}/workspaces", json={"name": "staging", "slug": "staging"}, headers=member).json()["data"]
        assert created["org_id"] == str(o1)
        assert created["name"] == "staging"
        assert created["slug"] == "staging"
        renamed = c.patch(f"/api/v1/orgs/{o1}/workspaces/{created['id']}", json={"name": "prod"}, headers=member).json()["data"]
        assert renamed["name"] == "prod"
        assert [w["name"] for w in c.get(f"/api/v1/orgs/{o1}/workspaces", headers=member).json()["data"]] == ["prod"]

        members = c.get(f"/api/v1/orgs/{o1}/workspaces/{created['id']}/members", headers=member).json()["data"]
        assert [(m["user_id"], m["email"], m["name"], m["service_account"], m["status"]) for m in members] == [
            (uid, "m@example.com", "m@example.com", False, "member")
        ]


def test_workspace_admin_can_list_org_member_candidates_without_org_member_read(tmp_path):
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    with TestClient(cp.app) as c:
        org_id = make_org(c, root, "o1")
        admin_id, admin = _member(c, cp, org_id, "admin@example.com")
        candidate_id, _ = _member(c, cp, org_id, "candidate@example.com")
        workspace_id = make_workspace(c, admin, "staging")
        workspace_admin = cp.headers_for(org_id, admin_id, workspace_id)

        candidates = c.get(f"/api/v1/orgs/{org_id}/workspaces/{workspace_id}/member-candidates", headers=workspace_admin)
        assert candidates.status_code == 200
        assert candidates.json()["data"] == [
            {"user_id": candidate_id, "email": "candidate@example.com", "name": "candidate@example.com", "service_account": False}
        ]

        assert admin_id != candidate_id


def test_workspace_member_lists_each_use_one_resource_query(tmp_path):
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    with TestClient(cp.app) as c:
        org_id = make_org(c, root, "o1")
        admin_id, admin = _member(c, cp, org_id, "admin@example.com")
        _member(c, cp, org_id, "candidate@example.com")
        workspace_id = make_workspace(c, admin, "staging")
        workspace_admin = cp.headers_for(org_id, admin_id, workspace_id)

        with captured_sql(cp.app) as member_statements:
            members = c.get(f"/api/v1/orgs/{org_id}/workspaces/{workspace_id}/members", headers=workspace_admin)
        with captured_sql(cp.app) as candidate_statements:
            candidates = c.get(f"/api/v1/orgs/{org_id}/workspaces/{workspace_id}/member-candidates", headers=workspace_admin)

        assert members.status_code == 200
        assert candidates.status_code == 200
        assert len([statement for statement in member_statements if statement.lstrip().startswith("SELECT")]) <= 8
        assert len([statement for statement in candidate_statements if statement.lstrip().startswith("SELECT")]) <= 8


def test_slug_is_unique_within_the_org_and_free_across_orgs(tmp_path):
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    with TestClient(cp.app) as c:
        o1 = make_org(c, root, "o1")
        o2 = make_org(c, root, "o2")
        assert c.post(f"/api/v1/orgs/{o1}/workspaces", json={"name": "Staging", "slug": "staging"}, headers=cp.headers(o1)).status_code == 200
        assert c.post(f"/api/v1/orgs/{o1}/workspaces", json={"name": "Other staging", "slug": "staging"}, headers=cp.headers(o1)).status_code == 409
        assert c.post(f"/api/v1/orgs/{o2}/workspaces", json={"name": "Staging", "slug": "staging"}, headers=cp.headers(o2)).status_code == 200


def test_slug_is_create_only(tmp_path):
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    with TestClient(cp.app) as c:
        o1 = make_org(c, root, "o1")
        org = cp.headers(o1)
        ws = make_workspace(c, org, "staging")
        assert c.patch(f"/api/v1/orgs/{o1}/workspaces/{ws}", json={"name": "prod", "slug": "prod"}, headers=org).status_code == 422
        workspace = c.get(f"/api/v1/orgs/{o1}/workspaces/{ws}", headers=org).json()["data"]
        assert (workspace["name"], workspace["slug"]) == ("staging", "staging")


def test_an_omitted_slug_is_derived_from_the_name(tmp_path):
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    with TestClient(cp.app) as c:
        o1 = make_org(c, root, "o1")
        org = cp.headers(o1)

        def create(name):
            return c.post(f"/api/v1/orgs/{o1}/workspaces", json={"name": name}, headers=org).json()["data"]["slug"]

        assert create("Staging") == "staging"
        assert create("Michel's EU / Prod!") == "michel-s-eu-prod"
        assert create("Staging") == "staging-2"
        assert create("Staging") == "staging-3"
        assert create("スタッフ") == "workspace"

        assert c.get(f"/api/v1/orgs/{o1}/workspaces/staging-2", headers=org).json()["data"]["name"] == "Staging"


def test_a_chosen_slug_is_never_silently_numbered(tmp_path):
    """Derivation resolves collisions; an explicit slug is a request that either lands or fails."""
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    with TestClient(cp.app) as c:
        o1 = make_org(c, root, "o1")
        org = cp.headers(o1)
        assert c.post(f"/api/v1/orgs/{o1}/workspaces", json={"name": "Staging"}, headers=org).json()["data"]["slug"] == "staging"
        assert c.post(f"/api/v1/orgs/{o1}/workspaces", json={"name": "Other", "slug": "staging"}, headers=org).status_code == 409


def test_workspace_routes_resolve_by_slug(tmp_path):
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    with TestClient(cp.app) as c:
        o1 = make_org(c, root, "o1")
        o2 = make_org(c, root, "o2")
        org = cp.headers(o1)
        ws = make_workspace(c, org, "staging")

        assert c.get(f"/api/v1/orgs/{o1}/workspaces/staging", headers=org).json()["data"]["id"] == str(ws)
        assert c.get(f"/api/v1/orgs/{o1}/workspaces/staging/members", headers=org).status_code == 200
        key = c.post(f"/api/v1/orgs/{o1}/workspaces/staging/inference-keys", json={"label": "k"}, headers=org).json()["data"]
        assert [k["id"] for k in c.get(f"/api/v1/orgs/{o1}/workspaces/{ws}/inference-keys", headers=org).json()["data"]] == [key["id"]]

        assert c.get(f"/api/v1/orgs/{o2}/workspaces/staging", headers=cp.headers(o2)).status_code == 404
        assert c.get(f"/api/v1/orgs/{o1}/workspaces/nope", headers=org).status_code == 404

        renamed = c.patch(f"/api/v1/orgs/{o1}/workspaces/staging", json={"name": "prod"}, headers=org).json()["data"]
        assert (renamed["name"], renamed["slug"]) == ("prod", "staging")
        assert c.delete(f"/api/v1/orgs/{o1}/workspaces/staging", headers=org).json()["data"]["id"] == str(ws)


@pytest.mark.parametrize("slug", ["Staging", "with space", "trailing-", "under_score", "0198f3c6-e1d8-7b4a-8c2d-1f4e5a6b7c8d", ""])
def test_slug_shapes_the_api_refuses(tmp_path, slug):
    """Lowercase alphanumeric words joined by single hyphens, and never uuid-shaped: a slug that
    could be read as an id would shadow the workspace whose id it is."""
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    with TestClient(cp.app) as c:
        o1 = make_org(c, root, "o1")
        assert c.post(f"/api/v1/orgs/{o1}/workspaces", json={"name": "n", "slug": slug}, headers=cp.headers(o1)).status_code == 422


def test_workspace_routes_404_outside_the_org(tmp_path):
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    with TestClient(cp.app) as c:
        o1 = make_org(c, root, "o1")
        o2 = make_org(c, root, "o2")
        ws = make_workspace(c, cp.headers(o1))
        assert c.get(f"/api/v1/orgs/{o1}/workspaces/{uuid7()}/inference-keys", headers=cp.headers(o1)).status_code == 404
        assert c.get(f"/api/v1/orgs/{o2}/workspaces/{ws}/inference-keys", headers=cp.headers(o2)).status_code == 404
        assert c.patch(f"/api/v1/orgs/{o2}/workspaces/{ws}", json={"name": "x"}, headers=cp.headers(o2)).status_code == 404
        assert c.get(f"/api/v1/orgs/{o2}/workspaces/{ws}/members", headers=cp.headers(o2)).status_code == 404
        assert c.get(f"/api/v1/orgs/{o2}/workspaces", headers=cp.headers(o2)).json()["data"] == []


def test_adding_a_non_org_member_is_a_conflict(tmp_path):
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    with TestClient(cp.app) as c:
        o1 = make_org(c, root, "o1")
        ws = make_workspace(c, cp.headers(o1))
        outsider = c.post(
            "/api/v1/auth/signup",
            json={"email": "out@example.com", "name": "Out", "password": "hunter2-hunter2"},
        ).json()["data"]["user_id"]
        assert c.put(f"/api/v1/orgs/{o1}/workspaces/{ws}/members/{outsider}", json={"role": "member"}, headers=cp.headers(o1)).status_code == 409
        assert c.put(f"/api/v1/orgs/{o1}/workspaces/{ws}/members/{uuid7()}", json={"role": "member"}, headers=cp.headers(o1)).status_code == 404


def test_key_operations_require_workspace_membership(tmp_path):
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    with TestClient(cp.app) as c:
        o1 = make_org(c, root, "o1")
        _, creator = _member(c, cp, o1, "creator@example.com", OrgRole.admin)
        _, outsider = _member(c, cp, o1, "orgmate@example.com")
        ws = make_workspace(c, creator)

        assert c.post(f"/api/v1/orgs/{o1}/workspaces/{ws}/inference-keys", json={"label": "k"}, headers=creator).status_code == 200
        assert c.get(f"/api/v1/orgs/{o1}/workspaces/{ws}/inference-keys", headers=creator).status_code == 200

        assert c.post(f"/api/v1/orgs/{o1}/workspaces/{ws}/inference-keys", json={"label": "k"}, headers=outsider).status_code == 403
        assert c.get(f"/api/v1/orgs/{o1}/workspaces/{ws}/inference-keys", headers=outsider).status_code == 403

        admin = cp.headers(o1)
        assert c.get(f"/api/v1/orgs/{o1}/workspaces/{ws}/inference-keys", headers=admin).status_code == 200


def test_membership_lifecycle_within_the_workspace(tmp_path):
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    with TestClient(cp.app) as c:
        o1 = make_org(c, root, "o1")
        _, creator = _member(c, cp, o1, "creator@example.com", OrgRole.admin)
        joiner, joiner_headers = _member(c, cp, o1, "joiner@example.com")
        ws = make_workspace(c, creator)

        assert c.get(f"/api/v1/orgs/{o1}/workspaces/{ws}/inference-keys", headers=joiner_headers).status_code == 403
        assert c.put(f"/api/v1/orgs/{o1}/workspaces/{ws}/members/{joiner}", json={"role": "member"}, headers=creator).status_code == 200
        assert c.put(f"/api/v1/orgs/{o1}/workspaces/{ws}/members/{joiner}", json={"role": "member"}, headers=creator).status_code == 200
        joiner_headers = cp.headers_for(o1, joiner, ws)
        assert c.get(f"/api/v1/orgs/{o1}/workspaces/{ws}/inference-keys", headers=joiner_headers).status_code == 200

        deleted = c.delete(f"/api/v1/orgs/{o1}/workspaces/{ws}/members/{joiner}", headers=creator).json()["data"]
        assert deleted["id"] == f"{joiner}/{ws}"
        assert c.delete(f"/api/v1/orgs/{o1}/workspaces/{ws}/members/{joiner}", headers=creator).status_code == 404
        assert c.get(f"/api/v1/orgs/{o1}/workspaces/{ws}/inference-keys", headers=joiner_headers).status_code == 403


def test_org_membership_removal_cascades_out_of_workspaces(tmp_path):
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    with TestClient(cp.app) as c:
        o1 = make_org(c, root, "o1")
        uid, member = _member(c, cp, o1, "m@example.com")
        ws = make_workspace(c, member)
        assert [m["user_id"] for m in c.get(f"/api/v1/orgs/{o1}/workspaces/{ws}/members", headers=cp.headers(o1)).json()["data"]] == [uid]

        assert c.delete(f"/api/v1/orgs/{o1}/users/{uid}", headers=cp.headers(o1)).status_code == 200
        assert c.get(f"/api/v1/orgs/{o1}/workspaces/{ws}/members", headers=cp.headers(o1)).json()["data"] == []

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
        k1 = c.post(f"/api/v1/orgs/{o1}/workspaces/{ws1}/inference-keys", json={"label": "k1"}, headers=org).json()["data"]
        k2 = c.post(f"/api/v1/orgs/{o1}/workspaces/{ws2}/inference-keys", json={"label": "k2"}, headers=org).json()["data"]

        c.post(f"/api/v1/orgs/{o1}/bundles/republish", headers=org)
        bundle = verify_bundle(SignedBundle.model_validate(c.get("/api/v1/bundle/latest", headers=org).json()["data"]), cp.bundle_key.public_key())
        assert {(k.key_id, str(k.workspace_id)) for k in bundle.keys} == {(UUID(k1["id"]), str(ws1)), (UUID(k2["id"]), str(ws2))}

        assert c.delete(f"/api/v1/orgs/{o1}/workspaces/{ws2}/inference-keys/{k1['id']}", headers=org).status_code == 404
        assert c.delete(f"/api/v1/orgs/{o1}/workspaces/{ws1}/inference-keys/{k1['id']}", headers=org).status_code == 200
        c.post(f"/api/v1/orgs/{o1}/bundles/republish", headers=org)
        bundle = verify_bundle(SignedBundle.model_validate(c.get("/api/v1/bundle/latest", headers=org).json()["data"]), cp.bundle_key.public_key())
        assert [k.key_id for k in bundle.keys] == [UUID(k2["id"])]
