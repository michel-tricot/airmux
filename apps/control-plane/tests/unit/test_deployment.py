from __future__ import annotations

from pathlib import Path

import yaml


def test_default_deployment_has_one_application_and_explicit_database_jobs():
    root = Path(__file__).resolve().parents[4]
    compose = yaml.safe_load((root / "docker-compose.yml").read_text())
    services = compose["services"]
    assert "name" not in compose
    assert set(services) == {"cli", "migrate", "taxonomy", "postgres"}
    assert services["cli"]["image"] == "${AIRMUX_IMAGE:-airmux:local}"
    assert services["cli"]["command"] == "airmux"
    assert "build" not in services["cli"]
    assert "env_file" not in services["cli"]
    assert services["cli"]["environment"]["AIRMUX_PUBLIC_SIGNUP"] == "${AIRMUX_PUBLIC_SIGNUP:-false}"
    assert services["cli"]["depends_on"] == {"taxonomy": {"condition": "service_completed_successfully"}}
    assert services["migrate"]["depends_on"] == {"postgres": {"condition": "service_healthy"}}
    assert services["taxonomy"]["depends_on"] == {"migrate": {"condition": "service_completed_successfully"}}
    assert all(services[name]["restart"] == "no" for name in ("migrate", "taxonomy"))


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
    image = "${AIRMUX_IMAGE:-airmux:local}"
    assert "setup" not in services
    application_services = ("control-plane", "data-plane-1", "data-plane-2", "console")
    assert all(services[name]["image"] == image for name in application_services)
    assert all("build" not in services[name] for name in application_services)
    assert all(services[name]["extends"] == {"file": "docker-compose.yml", "service": name} for name in ("migrate", "taxonomy"))
    assert {name for name, service in services.items() if service.get("ports")} == {"console"}
    assert "provider-secrets:/state/secrets:ro" in first["volumes"]
    assert "provider-secrets:/state/secrets:ro" in second["volumes"]
    assert "DATABASE_URL" not in first.get("environment", {})
    assert "DATABASE_URL" not in second.get("environment", {})
    assert services["postgres"]["volumes"] == ["split-pgdata:/var/lib/postgresql/data"]
    assert services["control-plane"]["environment"]["AIRMUX_PUBLIC_SIGNUP"] == "${AIRMUX_PUBLIC_SIGNUP:-false}"


def test_compose_layouts_do_not_share_database_volumes():
    root = Path(__file__).resolve().parents[4]
    compact = yaml.safe_load((root / "docker-compose.yml").read_text())
    split = yaml.safe_load((root / "docker-compose.split.yml").read_text())

    assert compact["services"]["postgres"]["volumes"] == ["pgdata:/var/lib/postgresql/data"]
    assert split["services"]["postgres"]["volumes"] == ["split-pgdata:/var/lib/postgresql/data"]


def test_container_healthchecks_use_role_health_endpoints():
    root = Path(__file__).resolve().parents[4]
    compact = yaml.safe_load((root / "docker-compose.yml").read_text())
    split = yaml.safe_load((root / "docker-compose.split.yml").read_text())

    assert "/healthz" in compact["services"]["cli"]["healthcheck"]["test"][-1]
    assert "/healthz" in split["services"]["data-plane-1"]["healthcheck"]["test"][-1]
    assert "/healthz" in split["services"]["data-plane-2"]["healthcheck"]["test"][-1]
    assert "/healthz" in split["services"]["control-plane"]["healthcheck"]["test"][-1]


def test_layouts_complete_database_jobs_before_serving():
    root = Path(__file__).resolve().parents[4]
    compact = yaml.safe_load((root / "docker-compose.yml").read_text())
    split = yaml.safe_load((root / "docker-compose.split.yml").read_text())

    assert "setup" not in compact["services"]
    assert "setup" not in split["services"]
    compact_services = compact["services"]
    assert compact_services["migrate"]["depends_on"]["postgres"]["condition"] == "service_healthy"
    assert compact_services["taxonomy"]["depends_on"]["migrate"]["condition"] == "service_completed_successfully"
    assert compact_services["cli"]["depends_on"]["taxonomy"]["condition"] == "service_completed_successfully"
    assert split["services"]["control-plane"]["depends_on"]["taxonomy"]["condition"] == "service_completed_successfully"
