from __future__ import annotations

import json
from uuid import uuid4

import httpx
import respx
from typer.testing import CliRunner

from cli.main import app

runner = CliRunner()


@respx.mock
def test_policy_create_and_update_preserve_typed_configuration(tmp_path, monkeypatch):
    org_id = str(uuid4())
    policy_id = str(uuid4())
    monkeypatch.setenv("AIRLLM_CLI_CONFIG", str(tmp_path / "config.toml"))
    monkeypatch.setenv("AIRLLM_MANAGEMENT_KEY", "sk-test-policies")
    monkeypatch.setenv("AIRLLM_ORG_ID", org_id)
    monkeypatch.setenv("AIRLLM_CONTROL_PLANE_URL", "http://cp.test")
    definition = {
        "target": {"kind": "all_keys"},
        "match": {"kind": "all_requests"},
        "action": {"kind": "budget", "period": "month", "amount_usd": "10.25", "sharing": "shared"},
    }
    policy = {
        "id": policy_id,
        "org_id": org_id,
        "workspace_id": str(uuid4()),
        "name": "Budget",
        "enabled": True,
        "priority": 100,
        "definition": definition,
        "created_at": "2026-09-08T00:00:00Z",
        "updated_at": "2026-09-08T00:00:00Z",
        "deleted_at": None,
    }
    path = tmp_path / "policy.json"
    path.write_text(json.dumps({"name": "Budget", "definition": definition}), encoding="utf-8")

    def create(incoming):
        assert json.loads(incoming.content)["definition"] == definition
        return httpx.Response(200, json={"data": policy})

    def update(incoming):
        assert json.loads(incoming.content) == {"enabled": False}
        return httpx.Response(200, json={"data": {**policy, "enabled": False}})

    respx.post(f"http://cp.test/api/v1/orgs/{org_id}/workspaces/production/policies").mock(side_effect=create)
    respx.patch(f"http://cp.test/api/v1/orgs/{org_id}/workspaces/production/policies/{policy_id}").mock(side_effect=update)
    created = runner.invoke(app, ["policies", "create", str(path), "-w", "production", "-f", "json"])
    assert created.exit_code == 0, created.output
    assert json.loads(created.stdout)[0]["definition"] == definition
    path.write_text('{"enabled": false}', encoding="utf-8")
    updated = runner.invoke(app, ["policies", "update", policy_id, str(path), "-w", "production", "-f", "json"])
    assert updated.exit_code == 0, updated.output
    assert json.loads(updated.stdout)[0]["enabled"] is False


def test_policy_create_rejects_invalid_json(tmp_path):
    path = tmp_path / "invalid.json"
    path.write_text('{"definition":', encoding="utf-8")
    result = runner.invoke(app, ["policies", "create", str(path), "-w", "production"])
    assert result.exit_code == 1
    assert "Invalid policy configuration" in result.stdout
