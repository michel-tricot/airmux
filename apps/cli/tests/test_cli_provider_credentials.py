from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import httpx
import pytest
from typer.testing import CliRunner

from api_models import ProviderCredentialOut
from cli import resources
from cli.main import app

runner = CliRunner()


class Client:
    def __init__(self, submitted: dict[str, object]) -> None:
        self.submitted = submitted

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def patch(self, path: str, json: dict[str, bool]) -> httpx.Response:
        self.submitted.update(path=path, body=json)
        now = datetime.now(tz=UTC)
        credential = ProviderCredentialOut(
            id=uuid4(),
            org_id=uuid4(),
            workspace_id=None,
            provider_id=uuid4(),
            provider_name="openai",
            name="production",
            priority=100,
            enabled=json["enabled"],
            version=1,
            status="unknown",
            status_at=None,
            fingerprint="1234",
            created_at=now,
            updated_at=now,
            scope="org",
        )
        return httpx.Response(200, request=httpx.Request("PATCH", f"http://control-plane{path}"), json={"data": credential.model_dump(mode="json")})


@pytest.mark.parametrize(("command", "enabled"), [("enable", True), ("disable", False)])
def test_provider_credential_state_commands_patch_the_existing_credential(monkeypatch, command: str, enabled: bool):
    submitted: dict[str, object] = {}
    monkeypatch.setattr(resources, "access_client", lambda _url: Client(submitted))
    monkeypatch.setattr(resources, "org_path", lambda path: f"/api/v1/organizations/org{path}")

    result = runner.invoke(app, ["provider-credentials", command, "credential-id"])

    assert result.exit_code == 0, result.output
    assert submitted == {
        "path": "/api/v1/organizations/org/provider-credentials/credential-id",
        "body": {"enabled": enabled},
    }
    assert f"{'Enabled' if enabled else 'Disabled'} production" in result.output


def test_disable_has_no_enable_option():
    result = runner.invoke(app, ["provider-credentials", "disable", "credential-id", "--enable"])

    assert result.exit_code == 2
    assert "No such option" in result.output
