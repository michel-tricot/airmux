from __future__ import annotations

import shlex

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
    taxonomy = tmp_path / "taxonomy.yml"
    taxonomy.write_text(yaml.safe_dump(TAXONOMY))
    result = runner.invoke(app, ["gateway", "init", "--taxonomy", str(taxonomy)])
    assert result.exit_code == 0, result.output
    assert (tmp_path / "tokkeeper.yml").is_file()
    key = (tmp_path / ".tokkeeper/inference.key").read_text().strip()
    assert key not in result.output
    result = runner.invoke(app, ["gateway", "validate"])
    assert result.exit_code == 0, result.output
    assert key not in result.output
    contents = {path: path.read_bytes() for path in (tmp_path / "tokkeeper.yml", tmp_path / "bundle.yml", tmp_path / ".tokkeeper/inference.key")}
    result = runner.invoke(app, ["gateway", "init", "--taxonomy", str(taxonomy)])
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
    config = yaml.safe_load((tmp_path / "tokkeeper.yml").read_text())
    assert config["data_plane"]["bundle"]["kind"] == "remote"
    assert config["control_plane"]["database"]["url"] == "${env:DATABASE_URL}"
    key = (tmp_path / ".tokkeeper/dataplane.key").read_text().strip()
    assert key not in result.output
    assert (tmp_path / ".tokkeeper/dataplane.key").stat().st_mode & 0o777 == 0o600
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
    (tmp_path / "tokkeeper.yml").write_text(yaml.safe_dump({"control_plane": {"bootstrap": {"token": token}}}))
    result = runner.invoke(app, ["control-plane", "validate"])
    assert result.exit_code != 0
    assert "bootstrap" in result.output
    assert token not in result.output
    assert "Traceback" not in result.output


@pytest.mark.parametrize("url", ["", "ftp://example.com", "https://", "https://example.com/console", "https://user:password@example.com"])
def test_control_plane_init_rejects_invalid_console_origins_without_writing_files(tmp_path, url):
    result = runner.invoke(app, ["control-plane", "init", "--directory", str(tmp_path), "--console-url", url])
    assert result.exit_code != 0
    assert not (tmp_path / "tokkeeper.yml").exists()
    assert not (tmp_path / ".tokkeeper").exists()


def test_control_plane_validate_rejects_unknown_configuration_fields(tmp_path):
    path = tmp_path / "tokkeeper.yml"
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


def test_initialization_prints_shell_safe_next_steps(tmp_path):
    directory = tmp_path / "my gateway"
    taxonomy = tmp_path / "taxonomy.yml"
    taxonomy.write_text(yaml.safe_dump(TAXONOMY))
    result = runner.invoke(app, ["gateway", "init", "--taxonomy", str(taxonomy), "--directory", str(directory)])
    assert result.exit_code == 0, result.output
    command = next(line.removeprefix("Start with: ") for line in result.output.splitlines() if line.startswith("Start with: "))
    assert shlex.split(command) == ["tokkeeper", "gateway", "serve", "--config", str(directory / "tokkeeper.yml")]


@pytest.mark.parametrize("group", ["gateway", "control-plane"])
def test_runtime_subcommand_help_is_available_without_the_extra(tmp_path, monkeypatch, group):
    monkeypatch.setattr("cli.runtime.find_spec", lambda _: None)
    result = runner.invoke(app, [group, "serve", "--help"])
    assert result.exit_code == 0, result.output
    assert "--config" in Text.from_ansi(result.output).plain
    assert "--port" in Text.from_ansi(result.output).plain
    result = runner.invoke(app, [group, "serve"])
    assert result.exit_code == 1
    assert f"tokkeeper[{group}]" in result.output


def test_unknown_configuration_variable_has_an_actionable_error(tmp_path):
    config = tmp_path / "tokkeeper.yml"
    config.write_text("control_plane:\n  console_url: ${var:missing}\n")
    result = runner.invoke(app, ["control-plane", "validate", "--config", str(config)])
    assert result.exit_code == 1
    assert "vars block does not define" in result.output
