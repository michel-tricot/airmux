from __future__ import annotations

import base64

from fastapi.testclient import TestClient
from helpers import make_org, setup_control_plane


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

        ids = [org["id"] for org in [*first["data"], *second["data"]]]
        assert ids == sorted(ids, reverse=True)
        assert {org["name"] for org in [*first["data"], *second["data"]]} == {"alpha", "bravo", "charlie", "delta"}
        assert first["page"]["next_cursor"] is not None
        assert second["page"]["next_cursor"] is None


def test_cursor_survives_renamed_anchor_and_excludes_concurrent_insert(tmp_path):
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    with TestClient(cp.app) as client:
        for name in ("alpha", "bravo", "delta", "echo"):
            make_org(client, root, name)
        first = client.get("/api/v1/organizations", params={"limit": 2}, headers=root).json()
        cursor = first["page"]["next_cursor"]

        anchor_id = first["data"][-1]["id"]
        assert client.patch(f"/api/v1/organizations/{anchor_id}", json={"name": "renamed"}, headers=root).status_code == 200
        inserted_id = make_org(client, root, "charlie")
        second = client.get("/api/v1/organizations", params={"limit": 3, "cursor": cursor}, headers=root).json()

        ids = [org["id"] for org in [*first["data"], *second["data"]]]
        assert inserted_id not in ids
        assert anchor_id not in {org["id"] for org in second["data"]}
        assert len(ids) == len(set(ids)) == 4


def test_invalid_and_oversized_cursors_are_generic(tmp_path):
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    with TestClient(cp.app) as client:
        make_org(client, root, "first")
        make_org(client, root, "second")
        first = client.get("/api/v1/organizations", params={"limit": 1}, headers=root).json()
        cursor = first["page"]["next_cursor"]
        assert cursor is not None

        invalid = ("%%%", "a" * 513, base64.urlsafe_b64encode(b"not-a-uuid").decode().rstrip("="))
        for token in invalid:
            response = client.get("/api/v1/organizations", params={"cursor": token}, headers=root)
            assert response.status_code == 422
            assert response.json() == {"detail": "invalid cursor"}
