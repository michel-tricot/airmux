from __future__ import annotations

import tomllib
from pathlib import Path

import yaml


def test_runtime_image_drops_root_privileges():
    dockerfile = Path(__file__).resolve().parents[4] / "Dockerfile"
    assert "USER 10001:10001" in dockerfile.read_text(encoding="utf-8")


def test_runtime_image_installs_backend_dependency_group():
    root = Path(__file__).resolve().parents[4]
    dockerfile = root / "Dockerfile"
    project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    content = dockerfile.read_text(encoding="utf-8")
    assert set(project["dependency-groups"]["backend"]) == {"cli", "control-plane", "data-plane"}
    assert content.count("uv sync --only-group backend --frozen") == 2
    assert "--no-install-package" not in content


def test_console_health_checks_the_control_plane():
    root = Path(__file__).resolve().parents[4]
    nginx = (root / "deploy" / "docker" / "nginx.conf.template").read_text(encoding="utf-8")

    assert "location = /healthz { proxy_pass http://$control_plane/healthz; }" in nginx
    assert "location = /healthz { return 200" not in nginx


def test_default_deployment_is_one_application_and_postgres():
    root = Path(__file__).resolve().parents[4]
    compose = yaml.safe_load((root / "docker-compose.yml").read_text())
    services = compose["services"]
    assert "name" not in compose
    assert set(services) == {"airllm", "postgres", "setup"}
    assert services["airllm"]["build"]["target"] == "all-in-one"
    assert services["airllm"]["image"] == services["setup"]["image"]
    assert "env_file" not in services["airllm"]
    assert services["setup"]["profiles"] == ["setup"]
    assert services["setup"]["env_file"]


def test_split_gateways_have_independent_state_and_no_provider_environment():
    root = Path(__file__).resolve().parents[4]
    compose = yaml.safe_load((root / "docker-compose.split.yml").read_text())
    services = compose["services"]
    first = services["data-plane-1"]
    second = services["data-plane-2"]
    assert "name" not in compose
    assert "gateway-1:/state/data-plane" in first["volumes"]
    assert "gateway-2:/state/data-plane" in second["volumes"]
    assert "env_file" not in first
    assert "env_file" not in second
    assert "env_file" not in services["control-plane"]
    assert services["setup"]["env_file"]
    assert services["control-plane"]["image"] == services["setup"]["image"]
    assert first["image"] == second["image"]
    assert "build" in first
    assert "build" not in second
    assert {name for name, service in services.items() if service.get("ports")} == {"console"}
    assert "provider-secrets:/state/secrets:ro" in first["volumes"]
    assert "provider-secrets:/state/secrets:ro" in second["volumes"]
    assert "DATABASE_URL" not in first.get("environment", {})
    assert "DATABASE_URL" not in second.get("environment", {})
    assert services["postgres"]["volumes"] == ["split-pgdata:/var/lib/postgresql/data"]


def test_compose_layouts_do_not_share_database_volumes():
    root = Path(__file__).resolve().parents[4]
    compact = yaml.safe_load((root / "docker-compose.yml").read_text())
    split = yaml.safe_load((root / "docker-compose.split.yml").read_text())

    assert compact["services"]["postgres"]["volumes"] == ["pgdata:/var/lib/postgresql/data"]
    assert split["services"]["postgres"]["volumes"] == ["split-pgdata:/var/lib/postgresql/data"]


def test_setup_connects_privately_and_reports_the_public_url():
    root = Path(__file__).resolve().parents[4]
    compact = yaml.safe_load((root / "docker-compose.yml").read_text())
    split = yaml.safe_load((root / "docker-compose.split.yml").read_text())
    digitalocean = (root / "deploy" / "digitalocean" / "compose.yml").read_text()

    assert compact["services"]["setup"]["command"][-4:] == [
        "--url",
        "${AIRLLM_PUBLIC_URL:-http://localhost:8080}",
        "--connect-url",
        "http://airllm:8080",
    ]
    assert split["services"]["setup"]["command"][-4:] == [
        "--url",
        "${AIRLLM_PUBLIC_URL:-http://localhost:8080}",
        "--connect-url",
        "http://console:8080",
    ]
    assert "      - https://${AIRLLM_DOMAIN:?Set the public domain}\n      - --connect-url\n      - http://airllm:8080" in digitalocean
