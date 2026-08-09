"""The request-lifecycle wiring in deps.py, observed through its durable effects.

management_claims must stamp the acting user for every authenticated request (audit
attribution depends on it), and get_session must bind each request to exactly one transaction
whose failure surfaces as an error, never as a phantom success.
"""

from __future__ import annotations

from fastapi.testclient import TestClient
from helpers import make_admin, run_in_db, setup_control_plane
from sqlalchemy import event
from sqlalchemy.orm import Session
from sqlmodel import col

from control_plane.models import AuditLog, Org


def test_api_requests_attribute_the_acting_user(tmp_path):
    """The full chain: bearer token -> management_claims -> set_actor -> GUC -> audit trigger."""
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    with TestClient(cp.app) as c:
        user = c.post("/v1/users", json={"email": "admin@example.com"}, headers=root).json()["data"]
        make_admin(tmp_path, user["id"])
        token = c.post("/v1/instance/instance-keys", json={"user_id": user["id"], "label": "t"}, headers=root).json()["data"]["token"]
        c.post("/v1/orgs", json={"name": "o2"}, headers={"authorization": f"Bearer {token}"})

    rows = run_in_db(tmp_path, lambda: AuditLog.find(order_by=col(AuditLog.id)))
    user_creation = next(r for r in rows if (r.table_name, r.action) == ("user", "create") and r.record_id == user["id"])
    assert user_creation.user_id is not None
    assert user_creation.user_id != user["id"]
    org_creation = next(r for r in rows if (r.table_name, r.action) == ("org", "create"))
    assert org_creation.user_id == user["id"]


def test_failed_commit_is_not_reported_as_success(tmp_path):
    cp = setup_control_plane(tmp_path)
    root = cp.headers()

    def refuse_commit(session):
        raise RuntimeError

    event.listen(Session, "before_commit", refuse_commit)
    try:
        with TestClient(cp.app, raise_server_exceptions=False) as c:
            resp = c.post("/v1/orgs", json={"name": "o1"}, headers=root)
            assert resp.status_code == 500
    finally:
        event.remove(Session, "before_commit", refuse_commit)
    assert run_in_db(tmp_path, Org.find) == []
