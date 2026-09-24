from __future__ import annotations

import asyncio
import signal
import subprocess
import time

import asyncpg
import httpx
import pytest
import yaml
from testcontainers.core.container import DockerContainer
from tests.acceptance.process_harness import uvicorn_port
from tests.installation.installation_support import run_cli


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
    token = (tmp_path / ".airmux/dataplane.key").read_text().strip()
    assert token not in initialized.stdout
    postgres = (
        DockerContainer("postgres:16")
        .with_env("POSTGRES_USER", "test")
        .with_env("POSTGRES_PASSWORD", "test")
        .with_env("POSTGRES_DB", "airmux")
        .with_exposed_ports(5432)
        .with_tmpfs_mount("/var/lib/postgresql/data")
    )
    with postgres:
        executable, environment = installation
        database = f"postgresql://test:test@{postgres.get_container_host_ip()}:{postgres.get_exposed_port(5432)}/airmux"
        asyncio.run(wait_for_database(database))
        installation = executable, {**environment, "DATABASE_URL": database}
        migrated = run_cli(installation, tmp_path, "control-plane", "migrate")
        assert "migrated empty ->" in migrated.stdout
        assert database not in migrated.stdout
        assert "already at" in run_cli(installation, tmp_path, "control-plane", "migrate").stdout
        log_path = tmp_path / "control-plane.log"
        with log_path.open("w") as log:
            process = subprocess.Popen(  # noqa: S603 the installed executable is supplied by the packaging test job
                [executable, "control-plane", "serve", "--port", "0"],
                cwd=tmp_path,
                env=installation[1],
                stdout=log,
                stderr=subprocess.STDOUT,
            )
            try:
                deadline = time.monotonic() + 20
                while (port := uvicorn_port(log_path)) is None and time.monotonic() < deadline:
                    assert process.poll() is None, log_path.read_text()
                    time.sleep(0.1)
                assert port is not None, log_path.read_text()
                with httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=2) as client:
                    wait_ready(client, process)
                    response = client.get("/api/v1/instance/oss/claim")
                    assert response.status_code == 200
                    assert response.json()["data"]["claimed"] is False
            finally:
                if process.poll() is None:
                    process.send_signal(signal.SIGTERM)
                assert process.wait(timeout=10) in {0, -signal.SIGTERM}
