from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from helpers import PROVIDER, setup_control_plane

from contract import uuid7


def test_create_returns_the_full_resource_and_patch_updates_it(tmp_path):
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    with TestClient(cp.app) as c:
        created = c.post("/api/v1/organizations", json={"name": "o1"}, headers=root).json()["data"]
        assert created["name"] == "o1"
        assert created["created_at"] is not None
        patched = c.patch(f"/api/v1/organizations/{created['id']}", json={"name": "Acme"}, headers=root).json()["data"]
        assert patched["name"] == "Acme"
        assert patched["id"] == created["id"]
        assert c.patch(f"/api/v1/organizations/{uuid7()}", json={"name": "x"}, headers=root).status_code == 404
        assert [o["name"] for o in c.get("/api/v1/organizations", headers=root).json()["data"]] == ["Acme"]


def test_organization_slug_lifecycle(tmp_path):
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    with TestClient(cp.app) as c:
        created = c.post("/api/v1/organizations", json={"name": "Acme Corporation", "slug": "acme"}, headers=root)
        assert created.status_code == 200, created.text
        org = created.json()["data"]
        assert org["slug"] == "acme"

        assert c.get("/api/v1/organizations/acme", headers=root).json()["data"]["id"] == org["id"]
        assert c.get("/api/v1/organizations/ACME", headers=root).json()["data"]["id"] == org["id"]
        assert c.get("/api/v1/organizations/acme/workspaces", headers=root).status_code == 200

        renamed = c.patch("/api/v1/organizations/acme", json={"name": "Acme, Inc."}, headers=root).json()["data"]
        assert (renamed["name"], renamed["slug"]) == ("Acme, Inc.", "acme")
        assert c.patch("/api/v1/organizations/acme", json={"slug": "renamed"}, headers=root).status_code == 422


def test_organization_slugs_are_globally_unique_and_derived_when_omitted(tmp_path):
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    with TestClient(cp.app) as c:

        def create(name):
            response = c.post("/api/v1/organizations", json={"name": name}, headers=root)
            assert response.status_code == 200, response.text
            return response.json()["data"]["slug"]

        assert create("Acme") == "acme"
        assert create("Acme") == "acme-2"
        assert create("スタッフ") == "organization"
        assert c.post("/api/v1/organizations", json={"name": "Another Acme", "slug": "acme"}, headers=root).status_code == 409


@pytest.mark.parametrize("slug", ["Acme", "with space", "trailing-", "under_score", "0198f3c6-e1d8-7b4a-8c2d-1f4e5a6b7c8d", ""])
def test_organization_slug_shapes_the_api_refuses(tmp_path, slug):
    cp = setup_control_plane(tmp_path)
    with TestClient(cp.app) as c:
        response = c.post("/api/v1/organizations", json={"name": "Acme", "slug": slug}, headers=cp.headers())
        assert response.status_code == 422


def test_mutation_inputs_reject_unknown_fields(tmp_path):
    cp = setup_control_plane(tmp_path)
    with TestClient(cp.app) as c:
        response = c.post("/api/v1/organizations", json={"name": "o1", "naem": "typo"}, headers=cp.headers())
        assert response.status_code == 422


def test_updated_at_tracks_modifications(tmp_path):
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    with TestClient(cp.app) as c:
        c.post("/api/v1/instance/taxonomy/providers", json=PROVIDER, headers=root)
        created = c.get("/api/v1/instance/taxonomy", headers=root).json()["data"]["providers"][0]
        assert created["updated_at"] == created["created_at"]
        c.post("/api/v1/instance/taxonomy/providers", json={**PROVIDER, "base_url": "https://eu.api.openai.com/v1"}, headers=root)
        second = c.get("/api/v1/instance/taxonomy", headers=root).json()["data"]["providers"][0]["updated_at"]
        assert second > created["updated_at"]
