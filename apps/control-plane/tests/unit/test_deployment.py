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
    assert set(project["dependency-groups"]["backend"]) == {"control-plane", "data-plane"}
    assert content.count("uv sync --only-group backend --frozen") == 2
    assert "--no-install-package" not in content
    assert "apps/cli" not in content


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
    assert set(services) == {"airllm", "postgres"}
    assert services["airllm"]["build"]["target"] == "all-in-one"
    assert "env_file" not in services["airllm"]


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


def test_compose_layouts_do_not_define_a_setup_service():
    root = Path(__file__).resolve().parents[4]
    compact = yaml.safe_load((root / "docker-compose.yml").read_text())
    split = yaml.safe_load((root / "docker-compose.split.yml").read_text())
    digitalocean = (root / "deploy" / "digitalocean" / "compose.yml").read_text()

    assert "setup" not in compact["services"]
    assert "setup" not in split["services"]
    assert "\n  setup:" not in digitalocean


def test_railway_deployment_has_postgres_and_persistent_state():
    root = Path(__file__).resolve().parents[4]
    railway = (root / ".railway" / "railway.ts").read_text()

    assert "postgres('postgres')" in railway
    assert "volume('airllm-state'" in railway
    assert "region: 'iad'" in railway
    assert "'/state': state" in railway
    assert "DATABASE_URL: database.env.DATABASE_URL" in railway
    assert "healthcheck: '/healthz'" in railway
    assert "replicas: 1" in railway
    assert "PORT: '8080'" in railway
    assert "AIRLLM_CONSOLE_URL" in railway


def test_release_publishes_versioned_multi_arch_image():
    root = Path(__file__).resolve().parents[4]
    workflow = (root / ".github" / "workflows" / "release.yml").read_text()

    assert "types: [published]" in workflow
    assert "packages: write" in workflow
    assert "attestations: write" in workflow
    assert "id-token: write" in workflow
    assert "target: all-in-one" in workflow
    assert "platforms: linux/amd64,linux/arm64" in workflow
    assert "type=semver,pattern={{version}}" in workflow
    assert "type=semver,pattern={{major}}.{{minor}}" in workflow
    assert "type=raw,value=latest,enable=${{ !github.event.release.prerelease }}" in workflow
    assert "push-to-registry: true" in workflow
    assert "gh release upload" in workflow
