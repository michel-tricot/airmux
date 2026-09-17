from __future__ import annotations

from pathlib import Path

import yaml


def test_default_deployment_is_one_application_and_postgres():
    root = Path(__file__).resolve().parents[4]
    compose = yaml.safe_load((root / "docker-compose.yml").read_text())
    services = compose["services"]
    assert "name" not in compose
    assert set(services) == {"airmux", "postgres"}
    assert services["airmux"]["image"] == "${AIRMUX_IMAGE:-airmux:local}"
    assert services["airmux"]["command"] == "airmux"
    assert "build" not in services["airmux"]
    assert "env_file" not in services["airmux"]
    assert services["airmux"]["environment"]["AIRMUX_PUBLIC_SIGNUP"] == "${AIRMUX_PUBLIC_SIGNUP:-false}"


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
    assert all(services[name]["image"] == image for name in ("setup", "control-plane", "data-plane-1", "data-plane-2", "console"))
    assert all("build" not in services[name] for name in ("setup", "control-plane", "data-plane-1", "data-plane-2", "console"))
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


def test_split_layout_defines_the_finite_setup_service():
    root = Path(__file__).resolve().parents[4]
    compact = yaml.safe_load((root / "docker-compose.yml").read_text())
    split = yaml.safe_load((root / "docker-compose.split.yml").read_text())
    digitalocean = yaml.load(
        (root / "deploy" / "digitalocean" / "compose.yml").read_text(),
        Loader=yaml.BaseLoader,  # noqa: S506 BaseLoader only constructs strings, lists, and maps, including Compose tags
    )

    assert "setup" not in compact["services"]
    assert split["services"]["setup"]["command"] == "setup"
    assert split["services"]["setup"]["restart"] == "no"
    assert "setup" not in digitalocean["services"]
