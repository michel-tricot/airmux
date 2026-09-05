from __future__ import annotations

import tomllib
from pathlib import Path


def test_fly_uses_the_shared_application_image_and_persistent_state():
    path = Path(__file__).resolve().parents[4] / "deploy/fly/fly.toml"
    config = tomllib.loads(path.read_text())
    assert (path.parent / config["build"]["dockerfile"]).is_file()
    assert config["build"]["build-target"] == "all-in-one"
    assert config["http_service"]["internal_port"] == 8080
    assert config["http_service"]["checks"][0]["path"] == "/healthz"
    assert config["mounts"]["destination"] == "/state"
