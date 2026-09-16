from __future__ import annotations

from fastapi.testclient import TestClient
from helpers import MODEL, PROVIDER, make_org, setup_control_plane, wait_for_publication

from control_plane.authz import Permission


def _bundles(client: TestClient, org_id, headers: dict[str, str]) -> list[dict]:
    return client.get(f"/api/v1/organizations/{org_id}/bundles", headers=headers).json()["data"]


def test_instance_admin_applies_a_taxonomy_atomically_and_publishes_once(tmp_path):
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    with TestClient(cp.app) as client:
        org_id = make_org(client, root)
        org = cp.headers(org_id)
        before = _bundles(client, org_id, org)

        response = client.post("/api/v1/instance/taxonomy", json={"providers": [PROVIDER], "models": [MODEL]}, headers=root)

        assert response.status_code == 200, response.text
        applied = response.json()["data"]
        assert applied["dry_run"] is False
        assert applied["providers"] == {"created": 1, "updated": 0, "unchanged": 0}
        assert applied["models"] == {"created": 1, "updated": 0, "unchanged": 0}
        assert _bundles(client, org_id, org) == before
        assert isinstance(applied["queued_revision"], int)
        wait_for_publication(client, org_id, org, applied["queued_revision"])
        taxonomy = client.get("/api/v1/instance/taxonomy", headers=root).json()["data"]
        assert [provider["name"] for provider in taxonomy["providers"]] == ["openai"]
        assert [model["name"] for model in taxonomy["models"]] == ["gpt-test"]


def test_taxonomy_dry_run_is_read_only(tmp_path):
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    with TestClient(cp.app) as client:
        org_id = make_org(client, root)
        org = cp.headers(org_id)
        before = _bundles(client, org_id, org)

        response = client.post(
            "/api/v1/instance/taxonomy",
            params={"dry_run": True},
            json={"providers": [PROVIDER], "models": [MODEL]},
            headers=root,
        )

        assert response.status_code == 200, response.text
        assert response.json()["data"] == {
            "dry_run": True,
            "providers": {"created": 1, "updated": 0, "unchanged": 0},
            "models": {"created": 1, "updated": 0, "unchanged": 0},
            "queued_revision": None,
        }
        assert client.get("/api/v1/instance/taxonomy", headers=root).json()["data"] == {"providers": [], "models": []}
        assert _bundles(client, org_id, org) == before


def test_taxonomy_apply_reports_unchanged_and_updated_entries(tmp_path):
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    with TestClient(cp.app) as client:
        body = {"providers": [PROVIDER], "models": [MODEL]}
        assert client.post("/api/v1/instance/taxonomy", json=body, headers=root).status_code == 200

        unchanged = client.post("/api/v1/instance/taxonomy", json=body, headers=root).json()["data"]
        assert unchanged["providers"] == {"created": 0, "updated": 0, "unchanged": 1}
        assert unchanged["models"] == {"created": 0, "updated": 0, "unchanged": 1}
        assert unchanged["queued_revision"] is None

        changed = client.post(
            "/api/v1/instance/taxonomy",
            json={"providers": [{**PROVIDER, "base_url": "https://other.example/v1"}], "models": [MODEL]},
            headers=root,
        ).json()["data"]
        assert changed["providers"] == {"created": 0, "updated": 1, "unchanged": 0}
        assert changed["models"] == {"created": 0, "updated": 0, "unchanged": 1}

        changed_modalities = client.post(
            "/api/v1/instance/taxonomy",
            json={"providers": [{**PROVIDER, "base_url": "https://other.example/v1"}], "models": [{**MODEL, "input_modalities": ["text", "image"]}]},
            headers=root,
        ).json()["data"]
        assert changed_modalities["providers"] == {"created": 0, "updated": 0, "unchanged": 1}
        assert changed_modalities["models"] == {"created": 0, "updated": 1, "unchanged": 0}


def test_taxonomy_apply_requires_manage_and_rejects_the_whole_invalid_document(tmp_path):
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    with TestClient(cp.app) as client:
        body = {"providers": [PROVIDER], "models": [MODEL]}
        assert client.post("/api/v1/instance/taxonomy", json=body, headers=cp.headers(permissions=[Permission.catalog_read])).status_code == 403

        invalid = client.post(
            "/api/v1/instance/taxonomy",
            json={
                "providers": [PROVIDER],
                "models": [
                    MODEL,
                    {**MODEL, "model_id": "orphan", "provider_id": "missing"},
                    {**MODEL, "model_id": "another-orphan", "provider_id": "also-missing"},
                ],
            },
            headers=root,
        )
        assert invalid.status_code == 404
        assert invalid.json() == {
            "detail": (
                "Unknown provider references: model 'orphan' requires provider 'missing'; model 'another-orphan' requires provider 'also-missing'"
            )
        }
        assert client.get("/api/v1/instance/taxonomy", headers=root).json()["data"] == {"providers": [], "models": []}
