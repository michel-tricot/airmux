from __future__ import annotations

import httpx
from typer.testing import CliRunner

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
        return httpx.Response(200, request=request, json={"data": {"id": "key", "boundary": "instance", "token": "shown-once"}})


def test_instance_flag_overrides_the_active_org_for_access_key_mint(monkeypatch):
    submitted = {}
    monkeypatch.setattr(resources, "active_profile", lambda: {"org_id": "active-org"})
    monkeypatch.setattr(resources, "access_client", lambda _url: Client(submitted))

    result = runner.invoke(app, ["access-keys", "mint", "--label", "ci", "--permission", "bundles.read", "--instance"])

    assert result.exit_code == 0, result.output
    assert submitted["path"] == "/v1/access-keys"
    assert submitted["body"]["org_id"] is None
    assert submitted["body"]["workspace_id"] is None
