from __future__ import annotations

import asyncio
import json
import os
import signal
import socket
import subprocess
import time
from pathlib import Path

import asyncpg
import httpx
import pytest
import yaml
from testcontainers.core.container import DockerContainer


@pytest.fixture
def installation(tmp_path):
    executable = os.environ.get("TOKKEEPER_INSTALL_BIN")
    if executable is None:
        pytest.skip("set TOKKEEPER_INSTALL_BIN to test an isolated installation")
    environment = {"PATH": os.environ["PATH"], "HOME": str(tmp_path), "NO_COLOR": "1"}
    return executable, environment


def run_cli(installation, directory, *args, check=True):
    executable, environment = installation
    return subprocess.run(  # noqa: S603 the installed executable is supplied by the packaging test job
        [executable, *args], cwd=directory, env=environment, text=True, capture_output=True, check=check, timeout=30
    )


def test_help_inventory_and_version_work_in_every_installation(installation, tmp_path):
    assert run_cli(installation, tmp_path, "--version").stdout.startswith("tokkeeper ")
    inventory = json.loads(run_cli(installation, tmp_path, "commands", "-f", "json").stdout)
    assert inventory
    for group in ("gateway", "control-plane"):
        help_text = run_cli(installation, tmp_path, group, "serve", "--help").stdout
        assert "--config" in help_text
        assert "--port" in help_text


def test_installed_gateway_initializes_with_the_shipped_taxonomy(installation, tmp_path):
    result = run_cli(installation, tmp_path, "gateway", "init")
    assert "taxonomy.yml" in result.stdout
    taxonomy = yaml.safe_load((tmp_path / "taxonomy.yml").read_text(encoding="utf-8"))
    assert taxonomy["providers"]
    assert taxonomy["models"]
    assert yaml.safe_load((tmp_path / "bundle.yml").read_text(encoding="utf-8"))["taxonomy"] == "taxonomy.yml"
    assert run_cli(installation, tmp_path, "gateway", "validate").returncode == 0


def test_internal_modules_are_bundled_in_one_distribution(installation, tmp_path):
    executable, environment = installation
    python = Path(executable).read_text(encoding="utf-8").splitlines()[0].removeprefix("#!")
    result = subprocess.run(  # noqa: S603 isolated tool interpreter built by the packaging test job
        [
            python,
            "-c",
            """
from importlib.metadata import PackageNotFoundError, distribution

tokkeeper = distribution("tokkeeper")
for name in ("tokkeeper-api-models", "tokkeeper-contract", "tokkeeper-control-plane", "tokkeeper-data-plane"):
    try:
        distribution(name)
    except PackageNotFoundError:
        pass
    else:
        raise AssertionError(f"unexpected internal distribution: {name}")

import api_models
import cli
import contract
import control_plane
import data_plane
from data_plane.heartbeat import VERSION

assert VERSION == tokkeeper.version
""",
        ],
        cwd=tmp_path,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr


def wait_ready(client, process):
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline and process.poll() is None:
        try:
            if client.get("/healthz").status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(0.1)
    pytest.fail("installed control plane did not become healthy; inspect control-plane.log")


async def wait_for_database(url):
    deadline = time.monotonic() + 30
    while True:
        try:
            connection = await asyncpg.connect(url, timeout=2)
        except (OSError, asyncpg.PostgresError):
            if time.monotonic() >= deadline:
                raise
            await asyncio.sleep(0.1)
        else:
            await connection.close()
            return


def test_installed_control_plane_migrates_and_serves_outside_the_checkout(installation, tmp_path):
    schema = yaml.safe_load(run_cli(installation, tmp_path, "control-plane", "openapi").stdout)
    assert "/api/v1/instance/oss/claim" in schema["paths"]
    initialized = run_cli(installation, tmp_path, "control-plane", "init")
    token = (tmp_path / ".tokkeeper/dataplane.key").read_text().strip()
    assert token not in initialized.stdout
    postgres = (
        DockerContainer("postgres:16")
        .with_env("POSTGRES_USER", "test")
        .with_env("POSTGRES_PASSWORD", "test")
        .with_env("POSTGRES_DB", "tokkeeper")
        .with_exposed_ports(5432)
        .with_tmpfs_mount("/var/lib/postgresql/data")
    )
    with postgres:
        executable, environment = installation
        database = f"postgresql://test:test@{postgres.get_container_host_ip()}:{postgres.get_exposed_port(5432)}/tokkeeper"
        asyncio.run(wait_for_database(database))
        installation = executable, {**environment, "DATABASE_URL": database}
        migrated = run_cli(installation, tmp_path, "control-plane", "migrate")
        assert "migrated empty ->" in migrated.stdout
        assert database not in migrated.stdout
        assert "already at" in run_cli(installation, tmp_path, "control-plane", "migrate").stdout
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
        with (tmp_path / "control-plane.log").open("w") as log:
            process = subprocess.Popen(  # noqa: S603 the installed executable is supplied by the packaging test job
                [executable, "control-plane", "serve", "--port", str(port)],
                cwd=tmp_path,
                env=installation[1],
                stdout=log,
                stderr=subprocess.STDOUT,
            )
            try:
                with httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=2) as client:
                    wait_ready(client, process)
                    response = client.get("/api/v1/instance/oss/claim")
                    assert response.status_code == 200
                    assert response.json()["data"]["claimed"] is False
            finally:
                if process.poll() is None:
                    process.send_signal(signal.SIGTERM)
                assert process.wait(timeout=10) in {0, -signal.SIGTERM}
