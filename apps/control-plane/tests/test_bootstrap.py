from __future__ import annotations

import yaml
from dotenv import dotenv_values
from fastapi.testclient import TestClient
from helpers import setup_control_plane

from contract import verify_inference_token
from control_plane.bootstrap import BootstrapSpec

SPEC = """
org: org-boot
providers:
  - provider_id: stub
    base_url: https://stub.example/v1
    credential_ref: env:STUB_KEY
models:
  - model_id: echo
    provider_id: stub
keys:
  - allowed_models: ["*"]
"""


def test_minimal_spec_gets_defaults():
    spec = BootstrapSpec.model_validate(yaml.safe_load("org: o1"))
    assert spec.providers == []
    assert spec.models == []
    assert [k.allowed_models for k in spec.keys] == [["*"]]


def test_full_spec_parses():
    spec = BootstrapSpec.model_validate(yaml.safe_load(SPEC))
    assert spec.providers[0].kind == "openai_compatible"
    assert spec.models[0].upstream_model == ""
    assert spec.models[0].capabilities == ["streaming", "tools"]
    assert len(spec.keys) == 1


def test_first_start_bootstraps_and_writes_tokens(tmp_path):
    cp = setup_control_plane(tmp_path)
    (tmp_path / "bootstrap.yml").write_text(SPEC, encoding="utf-8")
    with TestClient(cp.app) as c:
        env = dotenv_values(tmp_path / ".env")
        org = {"authorization": f"Bearer {env['GW_ORG_TOKEN']}"}
        dp = {"authorization": f"Bearer {env['GW_DP_TOKEN']}"}
        assert [m["id"] for m in c.get("/org/models", headers=org).json()] == ["echo"]
        assert [p["id"] for p in c.get("/org/providers", headers=org).json()] == ["stub"]
        latest = c.get("/v1/bundle/latest", headers=dp)
        assert latest.status_code == 200
        assert latest.json()["payload"]["org_id"] == "org-boot"
        assert latest.json()["payload"]["catalog"]["models"][0]["model_id"] == "echo"
        caller_token = env["AIRLLM_TOKEN"]
        assert caller_token is not None
        claims = verify_inference_token(caller_token, cp.token_key.public_key())
        assert claims is not None
        assert claims.org_id == "org-boot"
        minted = c.get("/instance/tokens", headers=cp.headers()).json()
        assert len(minted) == 2


def test_second_start_does_not_bootstrap_again(tmp_path):
    cp = setup_control_plane(tmp_path)
    (tmp_path / "bootstrap.yml").write_text(SPEC, encoding="utf-8")
    with TestClient(cp.app):
        first = dotenv_values(tmp_path / ".env")
    with TestClient(cp.app) as c:
        assert dotenv_values(tmp_path / ".env") == first
        org = {"authorization": f"Bearer {first['GW_ORG_TOKEN']}"}
        assert len(c.get("/org/models", headers=org).json()) == 1
        assert [b["version"] for b in c.get("/org/bundles", headers=org).json()] == [1]
        assert len(c.get("/instance/tokens", headers=cp.headers()).json()) == 2


def test_no_spec_file_boots_empty(tmp_path):
    cp = setup_control_plane(tmp_path)
    with TestClient(cp.app) as c:
        assert c.get("/instance/orgs", headers=cp.headers()).json() == []
        assert not (tmp_path / ".env").exists()
