from __future__ import annotations

from fastapi.testclient import TestClient
from helpers import make_admin, make_org, make_user, run_in_db, setup_control_plane
from sqlalchemy import event
from sqlalchemy.orm import Session
from sqlmodel import col

from control_plane.authz import Permission
from control_plane.models import AuditLog, Org


def test_api_requests_attribute_the_acting_user(tmp_path):
    """The full chain: bearer token -> authority -> set_actor -> GUC -> audit trigger."""
    cp = setup_control_plane(tmp_path)
    with TestClient(cp.app) as c:
        user = make_user(tmp_path, "admin@example.com")
        make_admin(tmp_path, user.id)
        token = c.post(
            "/api/v1/instance/management-keys",
            json={"label": "t", "permissions": [Permission.organizations_create]},
            headers=cp.headers_for(None, user.id),
        ).json()["data"]["token"]
        c.post("/api/v1/organizations", json={"name": "o2"}, headers={"authorization": f"Bearer {token}"})

    rows = run_in_db(tmp_path, lambda: AuditLog.find(order_by=col(AuditLog.id)))
    org_creation = next(r for r in rows if (r.table_name, r.action) == ("org", "create"))
    assert org_creation.user_id == str(user.id)


def test_failed_commit_is_not_reported_as_success(tmp_path):
    cp = setup_control_plane(tmp_path)
    root = cp.headers()

    def refuse_commit(session):
        raise RuntimeError

    event.listen(Session, "before_commit", refuse_commit)
    try:
        with TestClient(cp.app, raise_server_exceptions=False) as c:
            resp = c.post("/api/v1/organizations", json={"name": "o1"}, headers=root)
            assert resp.status_code == 500
    finally:
        event.remove(Session, "before_commit", refuse_commit)
    assert run_in_db(tmp_path, Org.find) == []


def test_refused_requests_explain_themselves(tmp_path):
    """Every dependency-level refusal carries a human-readable detail, so the console toast is actionable."""
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    with TestClient(cp.app) as c:
        org_id = make_org(c, root)
        org_headers = cp.headers(org_id=org_id)

        # Invalid bearer credential
        resp = c.get("/api/v1/organizations", headers={"authorization": "Bearer sk-cp-bogus"})
        assert resp.status_code == 401
        assert resp.json()["detail"] == "Invalid, expired, or revoked credential"

        # No credential at all
        resp = c.get("/api/v1/organizations")
        assert resp.status_code == 401
        assert resp.json()["detail"] == "Authentication required; sign in or provide a credential"

        # Org-scoped credential on an instance route
        resp = c.get("/api/v1/organizations", headers=org_headers)
        assert resp.status_code == 403
        assert "instance scope" in resp.json()["detail"]

        limited = cp.headers(org_id=org_id, permissions=[Permission.catalog_read])
        resp = c.get(f"/api/v1/organizations/{org_id}/workspaces", headers=limited)
        assert resp.status_code == 403
        assert resp.json()["detail"] == "Missing one of workspaces.read, organizations.read permissions for org scope"

        # Expired/invalid session cookie through the cookie door
        c.cookies.set("airmux_session", "bogus")
        resp = c.get("/api/v1/auth/me", headers={"X-Requested-With": "fetch"})
        assert resp.status_code == 401
        assert resp.json()["detail"] == "Your session has expired; sign in again"
