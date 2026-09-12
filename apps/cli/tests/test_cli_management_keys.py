from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import httpx
from typer.testing import CliRunner

from api_models import ManagementKeyMintedOut, Scope
from cli import resources
from cli.main import app

runner = CliRunner()


class Client:
    def __init__(self, submitted: dict) -> None:
        self.submitted = submitted

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def post(self, path: str, json: dict) -> httpx.Response:
        self.submitted.update(path=path, body=json)
        request = httpx.Request("POST", f"http://control-plane{path}")
        now = datetime.now(tz=UTC)
        key = ManagementKeyMintedOut(
            id=uuid4(),
            user_id=uuid4(),
            org_id=None,
            workspace_id=None,
            parent_id=None,
            prefix="sk-access",
            permissions=["bundles.read"],
            label="ci",
            expires_at=None,
            revoked_at=None,
            created_at=now,
            updated_at=now,
            deleted_at=None,
            scope=Scope.model_validate({"level": "instance"}),
            status="active",
            token="shown-once",
        )
        return httpx.Response(200, request=request, json={"data": key.model_dump(mode="json")})


def test_instance_flag_overrides_the_active_org_for_management_key_mint(monkeypatch):
    submitted = {}
    monkeypatch.setattr(resources, "access_client", lambda _url: Client(submitted))

    result = runner.invoke(app, ["management-keys", "mint", "--label", "ci", "--permission", "bundles.read", "--instance"])

    assert result.exit_code == 0, result.output
    assert submitted["path"] == "/api/v1/instance/management-keys"
    assert "org_id" not in submitted["body"]
    assert "workspace_id" not in submitted["body"]


def test_service_account_management_key_uses_the_dedicated_endpoint(monkeypatch):
    submitted = {}
    monkeypatch.setattr(resources, "access_client", lambda _url: Client(submitted))

    result = runner.invoke(
        app,
        [
            "management-keys",
            "mint",
            "--label",
            "ci",
            "--permission",
            "bundles.read",
            "--instance",
            "--service-account",
            "service-account-id",
        ],
    )

    assert result.exit_code == 0, result.output
    assert submitted["path"] == "/api/v1/service-accounts/service-account-id/management-keys"
    assert "user_id" not in submitted["body"]


def test_org_service_account_management_key_uses_the_dedicated_endpoint(monkeypatch):
    submitted = {}
    monkeypatch.setattr(resources, "access_client", lambda _url: Client(submitted))

    result = runner.invoke(
        app,
        [
            "management-keys",
            "mint",
            "--label",
            "ci",
            "--permission",
            "bundles.read",
            "--org",
            "org-id",
            "--service-account",
            "service-account-id",
        ],
    )

    assert result.exit_code == 0, result.output
    assert submitted["path"] == "/api/v1/orgs/org-id/service-accounts/service-account-id/management-keys"
    assert "user_id" not in submitted["body"]


def test_workspace_service_account_management_key_uses_the_dedicated_endpoint(monkeypatch):
    submitted = {}
    monkeypatch.setattr(resources, "access_client", lambda _url: Client(submitted))

    result = runner.invoke(
        app,
        [
            "management-keys",
            "mint",
            "--label",
            "ci",
            "--permission",
            "bundles.read",
            "--org",
            "org-id",
            "--workspace",
            "workspace-id",
            "--service-account",
            "service-account-id",
        ],
    )

    assert result.exit_code == 0, result.output
    assert submitted["path"] == "/api/v1/orgs/org-id/workspaces/workspace-id/service-accounts/service-account-id/management-keys"
    assert "user_id" not in submitted["body"]
