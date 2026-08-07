from __future__ import annotations

from fastapi.testclient import TestClient
from helpers import PROVIDER, run_in_db, setup_control_plane
from sqlmodel import col

from control_plane.models import AuditLog


def _audit_rows(tmp_path) -> list[AuditLog]:
    return run_in_db(tmp_path, lambda: AuditLog.find(order_by=col(AuditLog.id)))


def test_create_update_and_saveless_mutation_are_audited(tmp_path):
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    org = cp.headers("o1")
    with TestClient(cp.app) as c:
        c.post("/v1/orgs", json={"id": "o1"}, headers=root)
        c.post("/v1/taxonomy/providers", json=PROVIDER, headers=root)
        c.post("/v1/taxonomy/providers", json={**PROVIDER, "base_url": "https://eu.api.openai.com/v1"}, headers=root)
        key = c.post("/v1/org/keys", json={}, headers=org).json()["data"]
        c.delete(f"/v1/org/keys/{key['key_id']}", headers=org)

    rows = _audit_rows(tmp_path)
    actions = [(r.table_name, r.action) for r in rows]
    assert ("org", "create") in actions
    assert ("provider", "create") in actions
    assert ("provider", "update") in actions
    assert ("api_key", "create") in actions
    assert ("api_key", "update") in actions

    provider_update = next(r for r in rows if (r.table_name, r.action) == ("provider", "update"))
    assert provider_update.before is not None
    assert provider_update.after is not None
    assert provider_update.before["base_url"] == PROVIDER["base_url"]
    assert provider_update.after["base_url"] == "https://eu.api.openai.com/v1"
    assert provider_update.record_id == PROVIDER["provider_id"]
    assert provider_update.user_id is not None
    assert provider_update.occurred_at is not None

    revocation = next(r for r in rows if (r.table_name, r.action) == ("api_key", "update"))
    assert revocation.before is not None
    assert revocation.after is not None
    assert revocation.before["disabled"] is False
    assert revocation.after["disabled"] is True
    assert revocation.record_id == key["key_id"]

    creation = next(r for r in rows if (r.table_name, r.action) == ("org", "create"))
    assert creation.before is None
    assert creation.after is not None
    assert creation.after["id"] == "o1"


def test_snapshots_exclude_database_owned_timestamps(tmp_path):
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    with TestClient(cp.app) as c:
        c.post("/v1/orgs", json={"id": "o1"}, headers=root)

    creation = next(r for r in _audit_rows(tmp_path) if (r.table_name, r.action) == ("org", "create"))
    assert creation.after is not None
    assert "created_at" not in creation.after
    assert "updated_at" not in creation.after
    assert "deleted_at" not in creation.after


def test_audit_records_the_acting_user(tmp_path):
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    with TestClient(cp.app) as c:
        user = c.post("/v1/instance/users", json={"email": "admin@example.com", "instance_admin": True}, headers=root).json()["data"]
        token = c.post(f"/v1/instance/users/{user['id']}/tokens", json={}, headers=root).json()["data"]["token"]
        c.post("/v1/orgs", json={"id": "o2"}, headers={"authorization": f"Bearer {token}"})

    rows = _audit_rows(tmp_path)
    user_creation = next(r for r in rows if (r.table_name, r.action) == ("user", "create") and r.record_id == user["id"])
    assert user_creation.user_id != user["id"]
    org_creation = next(r for r in rows if (r.table_name, r.action) == ("org", "create"))
    assert org_creation.user_id == user["id"]


def test_membership_removal_writes_a_delete_log(tmp_path):
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    with TestClient(cp.app) as c:
        c.post("/v1/orgs", json={"id": "o1"}, headers=root)
        user = c.post("/v1/instance/users", json={"email": "m@example.com"}, headers=root).json()["data"]
        c.put(f"/v1/instance/users/{user['id']}/orgs/o1", headers=root)
        c.delete(f"/v1/instance/users/{user['id']}/orgs/o1", headers=root)

    rows = _audit_rows(tmp_path)
    deletion = next(r for r in rows if (r.table_name, r.action) == ("org_membership", "delete"))
    assert deletion.before is not None
    assert deletion.after is None
    assert deletion.before["user_id"] == user["id"]
    assert deletion.before["org_id"] == "o1"
    assert deletion.record_id == f"{user['id']}/o1"


def test_noop_upsert_writes_no_update_log(tmp_path):
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    with TestClient(cp.app) as c:
        c.post("/v1/taxonomy/providers", json=PROVIDER, headers=root)
        c.post("/v1/taxonomy/providers", json=PROVIDER, headers=root)

    rows = _audit_rows(tmp_path)
    assert [(r.table_name, r.action) for r in rows if r.table_name == "provider"] == [("provider", "create")]
