from __future__ import annotations

import os
import subprocess
import tomllib
from pathlib import Path

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
