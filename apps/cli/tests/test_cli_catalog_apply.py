from __future__ import annotations

import httpx
import yaml
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

    def post(self, path: str, params: dict, json: dict, timeout: float | None = None) -> httpx.Response:
        self.submitted.update(path=path, params=params, body=json, timeout=timeout)
        request = httpx.Request("POST", f"http://control-plane{path}")
        return httpx.Response(
            200,
            request=request,
            json={
                "data": {
                    "dry_run": params["dry_run"],
                    "providers": {"created": 1, "updated": 0, "unchanged": 0},
                    "models": {"created": 1, "updated": 0, "unchanged": 0},
                    "queued_revision": None,
                }
            },
        )


def test_catalog_apply_uploads_the_document_to_the_selected_control_plane(tmp_path, monkeypatch):
    submitted = {}
    document = {"providers": [{"provider_id": "openai"}], "models": [{"model_id": "gpt-test"}]}
    path = tmp_path / "taxonomy.yml"
    path.write_text(yaml.safe_dump(document), encoding="utf-8")
    monkeypatch.setattr(resources, "access_client", lambda _url: Client(submitted))

    result = runner.invoke(app, ["catalog", "apply", "--file", str(path), "--dry-run"])

    assert result.exit_code == 0, result.output
    assert submitted == {"path": "/api/v1/instance/taxonomy", "params": {"dry_run": True}, "body": document, "timeout": 120.0}
    assert "Dry run" in result.stdout
    assert "1 created, 0 updated, 0 unchanged" in result.stdout


def test_catalog_apply_refuses_invalid_yaml_before_the_request(tmp_path, monkeypatch):
    path = tmp_path / "taxonomy.yml"
    path.write_text("providers: [", encoding="utf-8")
    monkeypatch.setattr(resources, "access_client", lambda _url: (_ for _ in ()).throw(AssertionError("request must not be sent")))

    result = runner.invoke(app, ["catalog", "apply", "--file", str(path)])

    assert result.exit_code == 1
    assert "Invalid taxonomy YAML" in result.stdout
