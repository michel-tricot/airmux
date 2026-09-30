from __future__ import annotations

import os
import subprocess
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def run_release(tmp_path: Path, *, fail_migrate: bool = False) -> subprocess.CompletedProcess[str]:
    airmux = tmp_path / "airmux"
    calls = tmp_path / "calls"
    airmux.write_text(
        "#!/bin/sh\n"
        'printf "%s | %s\\n" "$AIRMUX_CONSOLE_URL" "$*" >> "$CALLS"\n'
        'if [ "${FAIL_MIGRATE:-}" = 1 ] && [ "$2" = migrate ]; then exit 7; fi\n'
    )
    airmux.chmod(0o755)
    environment: dict[str, str] = {
        **os.environ,
        "PATH": f"{tmp_path}:{os.environ['PATH']}",
        "CALLS": str(calls),
        "AIRMUX_CONFIG": "/app/deploy/docker/airmux.yml",
        "FLY_APP_NAME": "example-airmux",
        "FAIL_MIGRATE": "1" if fail_migrate else "0",
    }
    environment.pop("AIRMUX_CONSOLE_URL", None)
    return subprocess.run(  # noqa: S603 repository-owned startup script and temporary stub executable
        ["sh", str(ROOT / "deploy/docker/start.sh"), "release"],  # noqa: S607 fixed shell executable
        env=environment,
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def test_fly_release_migrates_then_applies_taxonomy(tmp_path: Path):
    result = run_release(tmp_path)
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "calls").read_text().splitlines() == [
        "https://example-airmux.fly.dev | control-plane migrate --config /app/deploy/docker/airmux.yml",
        "https://example-airmux.fly.dev | control-plane taxonomy --config /app/deploy/docker/airmux.yml --file /app/taxonomy/taxonomy.yml",
    ]


def test_fly_release_stops_when_migration_fails(tmp_path: Path):
    result = run_release(tmp_path, fail_migrate=True)
    assert result.returncode == 7
    assert len((tmp_path / "calls").read_text().splitlines()) == 1


def test_fly_config_runs_one_service_with_persistent_state():
    config = tomllib.loads((ROOT / "fly.toml").read_text())
    assert config["deploy"]["release_command"] == "release"
    assert config["http_service"]["internal_port"] == 8080
    assert config["http_service"]["auto_stop_machines"] == "off"
    assert config["mounts"] == {"source": "state", "destination": "/state"}
    assert config["http_service"]["checks"][0]["path"] == "/healthz"
