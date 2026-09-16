from __future__ import annotations

import shlex
import shutil
import subprocess

import pytest
import yaml
from rich.text import Text
from typer.testing import CliRunner

from cli.main import app

runner = CliRunner()
TAXONOMY = {
    "providers": [{"provider_id": "stub", "base_url": "http://127.0.0.1:9000"}],
    "models": [{"model_id": "echo", "provider_id": "stub", "input_modalities": ["text"], "output_modalities": ["text"]}],
}


def git_status(directory):
    git = shutil.which("git")
    assert git is not None
    subprocess.run([git, "init", "--quiet"], cwd=directory, check=True)  # noqa: S603 git is the test environment executable
    result = subprocess.run(  # noqa: S603 git is the test environment executable
        [git, "-c", "core.excludesFile=/dev/null", "status", "--porcelain", "--untracked-files=all"],
        cwd=directory,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout


@pytest.mark.parametrize("command", [[], ["gateway"], ["control-plane"]])
def test_runtime_commands_are_discoverable(command):
    result = runner.invoke(app, [*command, "--help"])
    assert result.exit_code == 0, result.output
    if not command:
        assert "gateway" in result.output
        assert "control-plane" in result.output
    else:
        assert "init" in result.output
        assert "serve" in result.output


def test_gateway_init_then_validate_needs_no_configuration_flags(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["gateway", "init"])
    assert result.exit_code == 0, result.output
    directory = tmp_path / ".airmux"
    assert (directory / "airmux.yml").is_file()
    assert (directory / "taxonomy.yml").is_file()
    assert ".airmux/taxonomy.yml" in result.output
    key = (directory / "inference.key").read_text().strip()
    status = git_status(tmp_path)
    assert ".airmux/inference.key" not in status
    assert ".airmux/taxonomy.yml" in status
    assert key not in result.output
    result = runner.invoke(app, ["gateway", "validate"])
    assert result.exit_code == 0, result.output
    assert "A real inference request verifies provider credentials and connectivity" in result.output
    assert "verified when serving" not in result.output
    assert key not in result.output
    contents = {
        path: path.read_bytes()
        for path in (
            directory / ".gitignore",
            directory / "airmux.yml",
            directory / "bundle.yml",
            directory / "taxonomy.yml",
            directory / "inference.key",
        )
    }
    result = runner.invoke(app, ["gateway", "init"])
    assert result.exit_code != 0
    assert "already exists" in result.output
    assert all(path.read_bytes() == original for path, original in contents.items())


@pytest.mark.parametrize("group", ["gateway", "control-plane"])
def test_explicit_missing_configuration_is_an_actionable_error(tmp_path, monkeypatch, group):
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, [group, "serve", "--config", "missing.yml"])
    assert result.exit_code != 0
    assert "missing.yml" in result.output
    assert "Traceback" not in result.output
    assert "init" in result.output


@pytest.mark.parametrize("group", ["gateway", "control-plane"])
@pytest.mark.parametrize("port", ["0", "65536"])
def test_serve_rejects_invalid_ports_before_starting(group, port):
    result = runner.invoke(app, [group, "serve", "--port", port])
    assert result.exit_code == 2
    assert "--port" in Text.from_ansi(result.output).plain


def test_control_plane_init_prepares_connected_configuration_without_a_database(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["control-plane", "init"])
    assert result.exit_code == 0, result.output
    config = yaml.safe_load((tmp_path / "airmux.yml").read_text())
    assert config["data_plane"]["bundle"]["kind"] == "remote"
    assert config["control_plane"]["database"]["url"] == "${env:DATABASE_URL}"
    key = (tmp_path / ".airmux/dataplane.key").read_text().strip()
    status = git_status(tmp_path)
    assert ".airmux/dataplane.key" not in status
    assert "airmux.yml" in status
    assert key not in result.output
    assert (tmp_path / ".airmux/dataplane.key").stat().st_mode & 0o777 == 0o600
    monkeypatch.setenv("DATABASE_URL", "postgresql://owner:password@127.0.0.1/example")
    result = runner.invoke(app, ["control-plane", "validate"])
    assert result.exit_code == 0, result.output
    result = runner.invoke(app, ["gateway", "validate"])
    assert result.exit_code == 0, result.output


def test_control_plane_openapi_needs_no_configuration(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["control-plane", "openapi"])
    assert result.exit_code == 0, result.output
    assert "/api/v1/instance/taxonomy" in yaml.safe_load(result.stdout)["paths"]


def test_runtime_validation_errors_do_not_print_credentials(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    token = "private-invalid-bootstrap-token"
    (tmp_path / "airmux.yml").write_text(yaml.safe_dump({"control_plane": {"bootstrap": {"token": token}}}))
    result = runner.invoke(app, ["control-plane", "validate"])
    assert result.exit_code != 0
    assert "bootstrap" in result.output
    assert token not in result.output
    assert "Traceback" not in result.output


@pytest.mark.parametrize("url", ["", "ftp://example.com", "https://", "https://example.com/console", "https://user:password@example.com"])
def test_control_plane_init_rejects_invalid_console_origins_without_writing_files(tmp_path, url):
    result = runner.invoke(app, ["control-plane", "init", "--directory", str(tmp_path), "--console-url", url])
    assert result.exit_code != 0
    assert not (tmp_path / "airmux.yml").exists()
    assert not (tmp_path / ".airmux").exists()


def test_control_plane_validate_rejects_unknown_configuration_fields(tmp_path):
    path = tmp_path / "airmux.yml"
    path.write_text("control_plane:\n  public_signups: true\n")
    result = runner.invoke(app, ["control-plane", "validate", "--config", str(path)])
    assert result.exit_code != 0
    assert "public_signups" in result.output


def test_control_plane_init_requires_database_url_when_validating(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert runner.invoke(app, ["control-plane", "init"]).exit_code == 0
    result = runner.invoke(app, ["control-plane", "validate"])
    assert result.exit_code != 0
    assert "database.url" in result.output


def test_initialization_prints_shell_safe_first_request(tmp_path, monkeypatch):
    monkeypatch.delenv("STUB_API_KEY", raising=False)
    directory = tmp_path / "my gateway"
    taxonomy = tmp_path / "taxonomy.yml"
    taxonomy.write_text(yaml.safe_dump(TAXONOMY))
    result = runner.invoke(app, ["gateway", "init", "--taxonomy", str(taxonomy), "--directory", str(directory)])
    assert result.exit_code == 0, result.output
    lines = [line.strip() for line in result.output.splitlines()]
    provider = next(line for line in lines if line.startswith("export STUB_API_KEY="))
    serve = next(line for line in lines if line.startswith("airmux gateway serve"))
    inference_key = next(line for line in lines if line.startswith("export AIRMUX_INFERENCE_KEY="))
    assert shlex.split(provider) == ["export", "STUB_API_KEY=your-provider-key"]
    assert shlex.split(serve) == ["airmux", "gateway", "serve", "--config", str(directory / "airmux.yml")]
    assert inference_key == f'export AIRMUX_INFERENCE_KEY="$(cat {shlex.quote(str(directory / "inference.key"))})"'
    assert "curl --fail http://127.0.0.1:8080/readyz" in lines
    assert any(line.startswith("curl --fail-with-body http://127.0.0.1:8080/inf/v1/chat/completions") for line in lines)
    assert "x-airmux-dialect" not in result.output.lower()
    assert '"model":"echo"' in result.output
    assert '"max_completion_tokens":16' in result.output


def test_initialization_uses_a_model_with_an_existing_provider_key(tmp_path, monkeypatch):
    taxonomy = {
        "providers": [
            {"provider_id": "missing", "base_url": "http://127.0.0.1:9000"},
            {"provider_id": "configured", "base_url": "http://127.0.0.1:9001"},
        ],
        "models": [
            {"model_id": "missing-model", "provider_id": "missing", "input_modalities": ["text"], "output_modalities": ["text"]},
            {"model_id": "configured-model", "provider_id": "configured", "input_modalities": ["text"], "output_modalities": ["text"]},
        ],
    }
    taxonomy_path = tmp_path / "taxonomy.yml"
    taxonomy_path.write_text(yaml.safe_dump(taxonomy))
    monkeypatch.setenv("CONFIGURED_API_KEY", "private-provider-key")
    result = runner.invoke(app, ["gateway", "init", "--taxonomy", str(taxonomy_path), "--directory", str(tmp_path / "gateway")])
    assert result.exit_code == 0, result.output
    assert 'CONFIGURED_API_KEY is set for "configured-model"' in result.output
    assert "export CONFIGURED_API_KEY=" not in result.output
    assert '"model":"configured-model"' in result.output
    assert "private-provider-key" not in result.output


@pytest.mark.parametrize("group", ["gateway", "control-plane"])
def test_runtime_subcommand_help_is_available(group):
    result = runner.invoke(app, [group, "serve", "--help"])
    assert result.exit_code == 0, result.output
    assert "--config" in Text.from_ansi(result.output).plain
    assert "--port" in Text.from_ansi(result.output).plain


def test_unknown_configuration_variable_has_an_actionable_error(tmp_path):
    config = tmp_path / "airmux.yml"
    config.write_text("control_plane:\n  console_url: ${var:missing}\n")
    result = runner.invoke(app, ["control-plane", "validate", "--config", str(config)])
    assert result.exit_code == 1
    assert "vars block does not define" in result.output
