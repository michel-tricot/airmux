from __future__ import annotations

import json
from uuid import uuid4

import httpx
import respx
from typer.testing import CliRunner

from cli.main import app

runner = CliRunner()


@respx.mock
def test_rule_create_preserves_typed_configuration(tmp_path, monkeypatch):
    org_id = str(uuid4())
    rule_id = str(uuid4())
    workspace_id = str(uuid4())
    monkeypatch.setenv("AIRLLM_CLI_CONFIG", str(tmp_path / "config.toml"))
    monkeypatch.setenv("AIRLLM_MANAGEMENT_KEY", "sk-test-rules")
    monkeypatch.setenv("AIRLLM_ORG_ID", org_id)
    monkeypatch.setenv("AIRLLM_CONTROL_PLANE_URL", "http://cp.test")
    definition = {
        "match": {"kind": "all_requests"},
        "action": {"kind": "budget", "period": "month", "amount_usd": "10.25", "sharing": "shared"},
    }
    rule = {
        "id": rule_id,
        "org_id": org_id,
        "workspace_id": workspace_id,
        "name": "Budget",
        "definition": definition,
        "created_at": "2026-09-08T00:00:00Z",
        "updated_at": "2026-09-08T00:00:00Z",
        "deleted_at": None,
    }
    path = tmp_path / "rule.json"
    path.write_text(json.dumps({"name": "Budget", "definition": definition}), encoding="utf-8")

    def create(incoming):
        assert json.loads(incoming.content)["definition"] == definition
        return httpx.Response(200, json={"data": rule})

    respx.post(f"http://cp.test/api/v1/orgs/{org_id}/workspaces/production/rules").mock(side_effect=create)
    created = runner.invoke(app, ["rules", "create", str(path), "-w", "production", "-f", "json"])
    assert created.exit_code == 0, created.output
    assert json.loads(created.stdout)[0]["definition"] == definition
