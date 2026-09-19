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
    monkeypatch.setenv("AIRMUX_CLI_CONFIG", str(tmp_path / "config.toml"))
    monkeypatch.setenv("AIRMUX_MANAGEMENT_KEY", "sk-test-policies")
    monkeypatch.setenv("AIRMUX_ORG_ID", org_id)
    monkeypatch.setenv("AIRMUX_CONTROL_PLANE_URL", "http://cp.test")
    definition = {
        "target": {"kind": "workspace"},
        "rules": [
            {
                "match": {"kind": "all_requests"},
                "action": {"kind": "request_limits", "max_output_tokens": 2048},
            }
        ],
    }
    policy = {
        "id": policy_id,
        "org_id": org_id,
        "workspace_id": str(uuid4()),
        "name": "Production",
        "enabled": True,
        "priority": 100,
        "definition": definition,
        "created_at": "2026-09-08T00:00:00Z",
        "updated_at": "2026-09-08T00:00:00Z",
        "deleted_at": None,
    }
    path = tmp_path / "policy.json"
    path.write_text(json.dumps({"name": "Production", "definition": definition}), encoding="utf-8")

    def create(incoming):
        assert json.loads(incoming.content)["definition"] == definition
        return httpx.Response(200, json={"data": policy})

    def update(incoming):
        assert json.loads(incoming.content) == {"enabled": False}
        return httpx.Response(200, json={"data": {**policy, "enabled": False}})

    respx.post(f"http://cp.test/api/v1/organizations/{org_id}/workspaces/production/policies").mock(side_effect=create)
    respx.patch(f"http://cp.test/api/v1/organizations/{org_id}/workspaces/production/policies/{policy_id}").mock(side_effect=update)
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


@respx.mock
def test_budget_status_preserves_exact_spending_and_pagination(tmp_path, monkeypatch):
    org_id, workspace_id, policy_id = (str(uuid4()) for _ in range(3))
    monkeypatch.setenv("AIRMUX_CLI_CONFIG", str(tmp_path / "config.toml"))
    monkeypatch.setenv("AIRMUX_MANAGEMENT_KEY", "sk-test-policies")
    monkeypatch.setenv("AIRMUX_ORG_ID", org_id)
    monkeypatch.setenv("AIRMUX_CONTROL_PLANE_URL", "http://cp.test")
    action = {"kind": "budget", "amount_usd": "0.000000000123", "period": "month", "aggregation": "per_key"}
    status = {
        "policy": {
            "id": policy_id,
            "org_id": org_id,
            "workspace_id": workspace_id,
            "name": "Budget",
            "enabled": True,
            "priority": 100,
            "definition": {"target": {"kind": "workspace"}, "rules": [{"match": {"kind": "all_requests"}, "action": action}]},
            "created_at": "2026-09-08T00:00:00Z",
            "updated_at": "2026-09-08T00:00:00Z",
            "deleted_at": None,
        },
        "computed_at": "2026-09-18T12:00:00Z",
        "budgets": [
            {
                "rule_index": 0,
                "amount_usd": action["amount_usd"],
                "period": "month",
                "aggregation": "per_key",
                "window_start": "2026-09-01T00:00:00Z",
                "window_end": "2026-10-01T00:00:00Z",
                "buckets": [
                    {
                        "bucket": {"kind": "key", "key_id": "key-b"},
                        "spent_usd": "0.000000000124",
                        "remaining_usd": "0",
                        "exhausted": True,
                    }
                ],
                "next_bucket": {"kind": "key", "key_id": "key-b"},
            }
        ],
    }

    def respond(incoming):
        assert dict(incoming.url.params) == {"rule_index": "0", "after_bucket": "key-a", "limit": "1"}
        return httpx.Response(200, json={"data": status})

    respx.get(f"http://cp.test/api/v1/organizations/{org_id}/workspaces/{workspace_id}/policies/{policy_id}/status").mock(side_effect=respond)
    result = runner.invoke(
        app,
        ["policies", "status", policy_id, "-w", workspace_id, "--rule-index", "0", "--after-bucket", "key-a", "--limit", "1", "-f", "json"],
    )
    assert result.exit_code == 0, result.output
    budget = json.loads(result.stdout)[0]
    assert budget["amount_usd"] == action["amount_usd"]
    assert budget["buckets"] == status["budgets"][0]["buckets"]
    assert budget["next_bucket"] == {"kind": "key", "key_id": "key-b"}
