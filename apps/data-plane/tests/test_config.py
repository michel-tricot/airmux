from __future__ import annotations

from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from pydantic import ValidationError

from contract import public_key_to_b64
from data_plane.bundle import LocalBundleConfig, RemoteBundleConfig
from data_plane.config import load_config

PUBLIC_KEY_B64 = public_key_to_b64(Ed25519PrivateKey.generate().public_key())


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
    # The repo config resolves the public key from a file the operator generates with `airllmcp keygen`.
    key = Ed25519PrivateKey.generate()
    (clean_env / ".airllm").mkdir()
    (clean_env / ".airllm" / "signing.pub").write_text(public_key_to_b64(key.public_key()), encoding="utf-8")
    (clean_env / ".airllm" / "dataplane.key").write_text("dp-token", encoding="utf-8")
    monkeypatch.setenv("GW_DATAPLANE_TOKEN", "dp-token")
    config = load_config()
    assert config.control_plane.url == "http://127.0.0.1:8000"
    assert config.control_plane.token == "dp-token"
    assert isinstance(config.bundle, RemoteBundleConfig)
    assert public_key_to_b64(config.bundle.verify_key) == public_key_to_b64(key.public_key())


def test_repo_config_takes_the_stack_control_plane_from_the_environment(clean_env, monkeypatch):
    """The same file serves a checkout and compose, so the address of the control plane moves with the environment."""
    repo_config = Path(__file__).resolve().parents[3] / "airllm.yml"
    (clean_env / "airllm.yml").write_text(repo_config.read_text(encoding="utf-8"), encoding="utf-8")
    (clean_env / ".airllm").mkdir()
    (clean_env / ".airllm" / "signing.pub").write_text(PUBLIC_KEY_B64, encoding="utf-8")
    (clean_env / ".airllm" / "dataplane.key").write_text("dp-token", encoding="utf-8")
    monkeypatch.setenv("GW_DATAPLANE_CONTROL_PLANE_URL", "http://control-plane:8000")

    assert load_config().control_plane.url == "http://control-plane:8000"


def test_malformed_verify_key_fails_at_load(clean_env):
    (clean_env / "airllm.yml").write_text("data_plane:\n  bundle:\n    kind: remote\n    verify_key: not-a-key\n", encoding="utf-8")
    with pytest.raises((ValidationError, ValueError)):
        load_config()


def test_defaults_apply_for_missing_sections(clean_env):
    config = f"data_plane:\n  bundle:\n    kind: remote\n    verify_key: {PUBLIC_KEY_B64}\n"
    (clean_env / "airllm.yml").write_text(config, encoding="utf-8")
    config = load_config()
    assert config.control_plane.url is None
    assert isinstance(config.bundle, RemoteBundleConfig)
    assert config.bundle.poll_interval_s == 30.0
    assert config.events.flush_interval_s == 5.0
    assert config.bundle.staleness_policy == "serve_and_warn"


def test_a_local_bundle_source_parses_without_a_verify_key(clean_env):
    """Local mode needs no signature, so it must not demand the key that verifies one."""
    (clean_env / "airllm.yml").write_text("data_plane:\n  bundle:\n    kind: local\n    path: ./bundle.yml\n", encoding="utf-8")
    config = load_config()
    assert isinstance(config.bundle, LocalBundleConfig)
    assert config.bundle.path == Path("./bundle.yml")
    assert config.control_plane.url is None
