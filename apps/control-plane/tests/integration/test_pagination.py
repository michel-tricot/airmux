from __future__ import annotations

import base64
import json

from fastapi.testclient import TestClient
from helpers import make_org, make_user, make_workspace, setup_control_plane


def _invalid_version_cursor(cursor: str) -> str:
    payload = json.loads(base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)))
    payload["v"] += 1
    return base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":")).encode()).decode().rstrip("=")


def test_collection_pages_cover_empty_middle_exact_and_final_pages(tmp_path):
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    with TestClient(cp.app) as client:
        empty = client.get("/api/v1/organizations", headers=root).json()
        assert empty == {"data": [], "page": {"next_cursor": None}}

        for name in ("alpha", "bravo", "charlie", "delta"):
            make_org(client, root, name)

        first = client.get("/api/v1/organizations", params={"limit": 2}, headers=root).json()
        second = client.get("/api/v1/organizations", params={"limit": 2, "cursor": first["page"]["next_cursor"]}, headers=root).json()

        assert [org["name"] for org in first["data"]] == ["alpha", "bravo"]
        assert [org["name"] for org in second["data"]] == ["charlie", "delta"]
        assert first["page"]["next_cursor"] is not None
        assert second["page"]["next_cursor"] is None


def test_cursor_survives_deleted_anchor_and_concurrent_insert(tmp_path):
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    with TestClient(cp.app) as client:
        org_ids = {name: make_org(client, root, name) for name in ("alpha", "bravo", "delta", "echo")}
        first = client.get("/api/v1/organizations", params={"limit": 2}, headers=root).json()
        cursor = first["page"]["next_cursor"]

        assert client.delete(f"/api/v1/organizations/{org_ids['bravo']}", headers=root).status_code == 200
        make_org(client, root, "charlie")
        second = client.get("/api/v1/organizations", params={"limit": 3, "cursor": cursor}, headers=root).json()

        assert [org["name"] for org in second["data"]] == ["charlie", "delta", "echo"]
        assert len({org["id"] for org in [*first["data"], *second["data"]]}) == 5


def test_invalid_mismatched_and_oversized_cursors_are_generic(tmp_path):
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    make_user(tmp_path, "member@example.com")
    with TestClient(cp.app) as client:
        first = client.get("/api/v1/users", params={"limit": 1, "service_account": False}, headers=root).json()
        cursor = first["page"]["next_cursor"]
        assert cursor is not None

        invalid = ("%%%", "a" * 513, _invalid_version_cursor(cursor))
        for token in invalid:
            response = client.get("/api/v1/users", params={"cursor": token}, headers=root)
            assert response.status_code == 422
            assert response.json() == {"detail": "invalid cursor"}

        changed_filter = client.get("/api/v1/users", params={"cursor": cursor, "service_account": True}, headers=root)
        assert changed_filter.status_code == 422
        assert changed_filter.json() == {"detail": "invalid cursor"}


def test_cursor_cannot_cross_tenant_scopes(tmp_path):
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    with TestClient(cp.app) as client:
        first_org = make_org(client, root, "first")
        second_org = make_org(client, root, "second")
        first_headers = cp.headers(first_org)
        for name in ("alpha", "bravo", "charlie"):
            make_workspace(client, first_headers, name)

        first = client.get(f"/api/v1/organizations/{first_org}/workspaces", params={"limit": 1}, headers=first_headers).json()
        response = client.get(
            f"/api/v1/organizations/{second_org}/workspaces",
            params={"cursor": first["page"]["next_cursor"]},
            headers=cp.headers(second_org),
        )

        assert response.status_code == 422
        assert response.json() == {"detail": "invalid cursor"}
