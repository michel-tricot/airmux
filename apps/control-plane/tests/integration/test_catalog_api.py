from __future__ import annotations

from fastapi.testclient import TestClient
from helpers import MODEL, PROVIDER, setup_control_plane


def test_the_catalog_refuses_a_credential(tmp_path):
    """Credentials are their own resource now. A taxonomy still carrying credential_ref has to fail
    rather than be ignored, or the operator believes they configured a key the provider does not have."""
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    with TestClient(cp.app) as c:
        bad = {**PROVIDER, "credential_ref": "env:OPENAI_API_KEY"}
        assert c.post("/api/v1/instance/taxonomy/providers", json=bad, headers=root).status_code == 422


def test_provider_pricing_multipliers_are_not_part_of_the_catalog(tmp_path):
    cp = setup_control_plane(tmp_path)
    with TestClient(cp.app) as c:
        bad = {**PROVIDER, "cache_read_multiplier": 0.5}
        assert c.post("/api/v1/instance/taxonomy/providers", json=bad, headers=cp.headers()).status_code == 422


def test_model_and_provider_upsert_converge(tmp_path):
    cp = setup_control_plane(tmp_path)
    root = cp.headers()
    with TestClient(cp.app) as c:
        c.post("/api/v1/instance/taxonomy/providers", json=PROVIDER, headers=root)
        assert c.post("/api/v1/instance/taxonomy/models", json={**MODEL, "input_price_per_mtok": 0.0}, headers=root).status_code == 422
        c.post("/api/v1/instance/taxonomy/models", json={**MODEL, "input_price_per_mtok": "0.0"}, headers=root)
        assert c.post("/api/v1/instance/taxonomy/models", json={**MODEL, "input_price_per_mtok": "0.15"}, headers=root).status_code == 200
        assert c.get("/api/v1/instance/taxonomy", headers=root).json()["data"]["models"][0]["input_price_per_mtok"] == "0.150000"
        updated = {**PROVIDER, "base_url": "https://other.example/v1"}
        assert c.post("/api/v1/instance/taxonomy/providers", json=updated, headers=root).status_code == 200
        assert c.get("/api/v1/instance/taxonomy", headers=root).json()["data"]["providers"][0]["base_url"] == "https://other.example/v1"


def test_model_with_unknown_provider_is_not_found(tmp_path):
    cp = setup_control_plane(tmp_path)
    with TestClient(cp.app) as c:
        response = c.post("/api/v1/instance/taxonomy/models", json={**MODEL, "provider_id": "nope"}, headers=cp.headers())
        assert response.status_code == 404
        assert response.json() == {"detail": "Unknown provider reference: model 'gpt-test' requires provider 'nope'"}
