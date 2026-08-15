"""The activity feed: the audit trail the triggers already write, read back over the API."""

from __future__ import annotations

from fastapi.testclient import TestClient
from helpers import make_org, make_workspace, setup_control_plane


def test_org_activity_reports_the_writes_in_that_org(tmp_path):
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    with TestClient(cp.app) as c:
        org = make_org(c, root, "o1")
        headers = cp.headers(org)
        workspace = make_workspace(c, headers, "staging")
        other = make_org(c, root, "o2")
        make_workspace(c, cp.headers(other), "elsewhere")

        activity = c.get("/v1/org/activity", headers=headers)
        assert activity.status_code == 200, activity.text
        entries = activity.json()["data"]

        assert ("workspace", str(workspace), "create") in [(e["table_name"], e["record_id"], e["action"]) for e in entries]
        assert all(str(other) not in e["record_id"] for e in entries)
        assert entries == sorted(entries, key=lambda e: e["id"], reverse=True)


def test_activity_never_serves_the_row_snapshots(tmp_path):
    """before and after hold whole rows, token hashes included; the feed reports what changed, not the columns."""
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    with TestClient(cp.app) as c:
        org = make_org(c, root, "o1")
        headers = cp.headers(org)
        workspace = make_workspace(c, headers, "staging")
        c.post(f"/v1/org/workspaces/{workspace}/inference-keys", json={"label": "k"}, headers=headers)

        for entry in c.get("/v1/org/activity", headers=headers).json()["data"]:
            assert "before" not in entry
            assert "after" not in entry
            assert "token_hash" not in str(entry)


def test_instance_activity_spans_every_org(tmp_path):
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    with TestClient(cp.app) as c:
        first = make_org(c, root, "o1")
        second = make_org(c, root, "o2")

        entries = c.get("/v1/instance/activity", headers=root).json()["data"]
        recorded = {e["record_id"] for e in entries}
        assert {str(first), str(second)} <= recorded


def test_org_activity_is_limited_and_ordered_newest_first(tmp_path):
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    with TestClient(cp.app) as c:
        org = make_org(c, root, "o1")
        headers = cp.headers(org)
        for i in range(4):
            make_workspace(c, headers, f"ws{i}")

        entries = c.get("/v1/org/activity", params={"limit": 2}, headers=headers).json()["data"]
        assert len(entries) == 2
        assert entries[0]["id"] > entries[1]["id"]
        assert c.get("/v1/org/activity", params={"limit": 0}, headers=headers).status_code == 422
        assert c.get("/v1/org/activity", params={"limit": 201}, headers=headers).status_code == 422
        assert c.get("/v1/instance/activity", params={"limit": 201}, headers=root).status_code == 422
