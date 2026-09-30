from __future__ import annotations

import os
import subprocess
import tomllib
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def run_migrate(tmp_path: Path, *, console_url: str | None) -> subprocess.CompletedProcess[str]:
    airmux = tmp_path / "airmux"
    calls = tmp_path / "calls"
    airmux.write_text('#!/bin/sh\nprintf "%s | %s\\n" "$AIRMUX_CONSOLE_URL" "$*" >> "$CALLS"\n')
    airmux.chmod(0o755)
    environment: dict[str, str] = {
        **os.environ,
        "PATH": f"{tmp_path}:{os.environ['PATH']}",
        "CALLS": str(calls),
        "AIRMUX_CONFIG": "/app/deploy/docker/airmux.yml",
        "FLY_APP_NAME": "example-airmux",
    }
    if console_url is None:
        environment.pop("AIRMUX_CONSOLE_URL", None)
    else:
        environment["AIRMUX_CONSOLE_URL"] = console_url
    return subprocess.run(  # noqa: S603 repository-owned startup script and temporary stub executable
        ["sh", str(ROOT / "deploy/docker/start.sh"), "migrate"],  # noqa: S607 fixed shell executable
        env=environment,
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def test_start_does_not_infer_console_url_from_fly_name(tmp_path: Path):
    result = run_migrate(tmp_path, console_url=None)
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "calls").read_text().splitlines() == ["http://localhost:8080 | control-plane migrate --config /app/deploy/docker/airmux.yml"]
    result = run_migrate(tmp_path, console_url="https://example-airmux.fly.dev")
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "calls").read_text().splitlines()[-1] == (
        "https://example-airmux.fly.dev | control-plane migrate --config /app/deploy/docker/airmux.yml"
    )


def test_fly_config_runs_one_service_with_persistent_state():
    assert not (ROOT / "fly.toml").exists()
    assert not (ROOT / "deploy/fly.toml").exists()
    config = tomllib.loads((ROOT / "deploy/fly/fly.toml").read_text())
    assert "app" not in config
    assert "primary_region" not in config
    assert "env" not in config
    assert config["build"] == {"image": "ghcr.io/michel-tricot/airmux:latest"}
    assert config["deploy"]["release_command"] == "migrate"
    assert config["http_service"]["internal_port"] == 8080
    assert config["http_service"]["auto_stop_machines"] == "off"
    assert config["mounts"] == {"source": "state", "destination": "/state"}
    assert config["http_service"]["checks"][0]["path"] == "/healthz"


def test_fly_guide_shows_the_full_update_command():
    guide = (ROOT / "docs/deployment/fly.mdx").read_text()
    assert "## Update" in guide
    update = guide.split("## Update", maxsplit=1)[1]
    assert "fly deploy \\" in update
    assert "--config deploy/fly/fly.toml" in update
    assert '--env "AIRMUX_CONSOLE_URL=$PUBLIC_URL"' in update
    assert 'fly ssh console --app "$APP_NAME" --user airmux --command "/app/deploy/docker/start.sh taxonomy"' in update


def test_fly_workflow_deploys_and_updates_catalog_on_manual_dispatch():
    workflow = yaml.safe_load((ROOT / ".github/workflows/deploy-fly.yml").read_text())
    assert workflow["name"] == "Deploy - Fly"
    assert set(workflow[True]) == {"workflow_dispatch"}
    assert workflow[True]["workflow_dispatch"] is None
    assert workflow["concurrency"]["group"] == "deploy-fly-${{ vars.FLY_APP_NAME }}"
    assert workflow["concurrency"]["cancel-in-progress"] is False
    job = workflow["jobs"]["deploy"]
    assert job["if"] == "github.ref == 'refs/heads/main'"
    deployment = next(step for step in job["steps"] if step.get("name") == "Deploy and update catalog")
    assert deployment["env"]["FLY_API_TOKEN"] == "${{ secrets.FLY_API_TOKEN }}"
    assert deployment["env"]["APP_NAME"] == "${{ vars.FLY_APP_NAME }}"
    assert deployment["env"]["REGION"] == "${{ vars.FLY_REGION }}"
    assert deployment["env"]["PUBLIC_URL"] == "${{ vars.AIRMUX_CONSOLE_URL }}"
    commands = deployment["run"]
    assert 'test -n "$APP_NAME"' in commands
    assert 'test -n "$REGION"' in commands
    assert commands.index("fly deploy") < commands.index("fly ssh console") < commands.index("curl -fsS")
    assert "--config deploy/fly/fly.toml" in commands
    assert '--primary-region "$REGION"' in commands
    assert "--ha=false" in commands
