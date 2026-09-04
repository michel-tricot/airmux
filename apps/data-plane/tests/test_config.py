from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from contract import FileStoreConfig
from data_plane.bundle import LocalBundleConfig, RemoteBundleConfig
from data_plane.config import Config, DevNullOutboxConfig, SqliteOutboxConfig, load_config


@pytest.fixture
def clean_env(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    for var in ("GW_CONFIG", "GW_DEV", "GW_DATAPLANE_CONTROL_PLANE_URL"):
        monkeypatch.delenv(var, raising=False)
    return tmp_path


def test_repo_config_parses_through_the_data_plane_loader(clean_env, monkeypatch):
    """The config the repo ships has to keep loading; nothing else guards an edit to it.

    Where the token comes from is the config file's business, so both sources are laid out with the
    same value: this stays green whether it names the keygen file or the environment variable.
    """
    repo_config = Path(__file__).resolve().parents[3] / "airllm.yml"
    (clean_env / "airllm.yml").write_text(repo_config.read_text(encoding="utf-8"), encoding="utf-8")
    (clean_env / ".airllm").mkdir()
    (clean_env / ".airllm" / "dataplane.key").write_text("dp-token", encoding="utf-8")
    monkeypatch.setenv("GW_DATAPLANE_TOKEN", "dp-token")
    config = load_config()
    assert isinstance(config.bundle, RemoteBundleConfig)
    assert config.bundle.control_plane.url == "http://127.0.0.1:8000"
    assert config.bundle.control_plane.token == "dp-token"
    assert isinstance(config.events, SqliteOutboxConfig)
    assert config.events.control_plane == config.bundle.control_plane


def test_connected_configs_own_independent_control_plane_links():
    config = Config.model_validate(
        {
            "bundle": {
                "kind": "remote",
                "control_plane": {"url": "http://bundle-cp.test", "token": "bundle-token"},
            },
            "events": {
                "kind": "sqlite",
                "control_plane": {"url": "http://events-cp.test", "token": "events-token"},
            },
        }
    )

    assert isinstance(config.bundle, RemoteBundleConfig)
    assert isinstance(config.events, SqliteOutboxConfig)
    assert config.bundle.control_plane.url == "http://bundle-cp.test"
    assert config.events.control_plane.url == "http://events-cp.test"
    assert not hasattr(config, "control_plane")


def test_the_legacy_top_level_control_plane_link_is_rejected():
    with pytest.raises(ValidationError, match="control_plane"):
        Config.model_validate(
            {
                "control_plane": {"url": "http://cp.test", "token": "dp-token"},
                "bundle": {"kind": "local", "path": "bundle.yml"},
            }
        )


def test_repo_config_takes_the_stack_control_plane_from_the_environment(clean_env, monkeypatch):
    """The same file serves a checkout and compose, so the address of the control plane moves with the environment."""
    repo_config = Path(__file__).resolve().parents[3] / "airllm.yml"
    (clean_env / "airllm.yml").write_text(repo_config.read_text(encoding="utf-8"), encoding="utf-8")
    (clean_env / ".airllm").mkdir()
    (clean_env / ".airllm" / "dataplane.key").write_text("dp-token", encoding="utf-8")
    monkeypatch.setenv("GW_DATAPLANE_CONTROL_PLANE_URL", "http://control-plane:8000")

    bundle = load_config().bundle
    assert isinstance(bundle, RemoteBundleConfig)
    assert bundle.control_plane.url == "http://control-plane:8000"


def test_remote_bundle_rejects_a_configured_verify_key(clean_env):
    config = (
        "data_plane:\n  bundle:\n    kind: remote\n"
        "    control_plane: {url: http://cp.test, token: dp-token}\n"
        "    verify_key: no-longer-configured-here\n"
    )
    (clean_env / "airllm.yml").write_text(config, encoding="utf-8")
    with pytest.raises((ValidationError, ValueError)):
        load_config()


def test_defaults_apply_to_a_standalone_data_plane(clean_env):
    (clean_env / "airllm.yml").write_text("data_plane:\n  bundle:\n    kind: local\n    path: ./bundle.yml\n", encoding="utf-8")
    config = load_config()
    assert not hasattr(config, "control_plane")
    assert isinstance(config.bundle, LocalBundleConfig)
    assert isinstance(config.events, DevNullOutboxConfig)
    assert config.bundle.reload_interval_s == 2.0


def test_outbox_kind_discriminates_the_config(clean_env):
    config = "data_plane:\n  bundle:\n    kind: local\n    path: ./bundle.yml\n  events:\n    kind: devnull\n"
    (clean_env / "airllm.yml").write_text(config, encoding="utf-8")

    assert isinstance(load_config().events, DevNullOutboxConfig)


def test_remote_bundle_requires_a_control_plane(clean_env):
    config = "data_plane:\n  bundle:\n    kind: remote\n"
    (clean_env / "airllm.yml").write_text(config, encoding="utf-8")

    with pytest.raises(ValidationError, match="control_plane"):
        load_config()


def test_remote_bundle_rejects_the_removed_org_selector():
    with pytest.raises(ValidationError, match="org"):
        Config.model_validate(
            {
                "bundle": {
                    "kind": "remote",
                    "control_plane": {"url": "http://cp.test", "token": "dp-token"},
                    "org": "0198f3c6-e1d8-7b4a-8c2d-1f4e5a6b7c8d",
                }
            }
        )


def test_sqlite_outbox_requires_a_control_plane(clean_env):
    config = "data_plane:\n  bundle:\n    kind: local\n    path: ./bundle.yml\n  events:\n    kind: sqlite\n"
    (clean_env / "airllm.yml").write_text(config, encoding="utf-8")

    with pytest.raises(ValidationError, match="control_plane"):
        load_config()


@pytest.mark.parametrize("control_plane", [{"url": "http://cp.test"}, {"token": "dp-token"}])
def test_control_plane_link_is_complete_or_absent(control_plane):
    with pytest.raises(ValidationError):
        Config.model_validate(
            {
                "bundle": {"kind": "local", "path": "bundle.yml"},
                "events": {"kind": "sqlite", "control_plane": control_plane},
            }
        )


def test_remote_intervals_must_be_positive():
    with pytest.raises(ValidationError) as error:
        Config.model_validate(
            {
                "bundle": {
                    "kind": "remote",
                    "control_plane": {"url": "http://cp.test", "token": "dp-token"},
                    "poll_interval_s": 0,
                    "heartbeat_interval_s": 0,
                },
                "events": {
                    "kind": "sqlite",
                    "control_plane": {"url": "http://cp.test", "token": "dp-token"},
                    "flush_interval_s": 0,
                },
            }
        )

    assert {issue["loc"][-1] for issue in error.value.errors()} == {"heartbeat_interval_s", "poll_interval_s", "flush_interval_s"}


def test_local_reload_interval_must_be_positive():
    with pytest.raises(ValidationError, match="reload_interval_s"):
        Config.model_validate({"bundle": {"kind": "local", "path": "bundle.yml", "reload_interval_s": 0}})


@pytest.mark.parametrize("control_plane_url", ["http://control-plane:8000", "http://127.0.0.1:8000"])
def test_container_config_separates_gateway_state_from_shared_credentials(tmp_path, monkeypatch, control_plane_url):
    container_config = Path(__file__).resolve().parents[3] / "deploy/docker/airllm.yml"
    (tmp_path / "airllm.yml").write_text(container_config.read_text().replace("/state", str(tmp_path)))
    (tmp_path / "runtime").mkdir()
    (tmp_path / "runtime/dataplane.key").write_text("data-plane-token")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GW_CONFIG", str(tmp_path / "airllm.yml"))
    monkeypatch.setenv("GW_DATAPLANE_CONTROL_PLANE_URL", control_plane_url)
    monkeypatch.delenv("DATABASE_URL", raising=False)

    config = load_config()

    assert isinstance(config.bundle, RemoteBundleConfig)
    assert config.bundle.control_plane.url == control_plane_url
    assert config.bundle.control_plane.token == "data-plane-token"
    assert config.bundle.cache_dir == tmp_path / "data-plane"
    assert isinstance(config.events, SqliteOutboxConfig)
    assert config.events.control_plane == config.bundle.control_plane
    assert config.events.cache_dir == config.bundle.cache_dir
    assert config.secrets == FileStoreConfig(root=tmp_path / "secrets")
