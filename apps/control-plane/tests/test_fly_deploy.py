from __future__ import annotations

import tomllib
from pathlib import Path

import pytest


@pytest.mark.parametrize("config_name", ["backend.toml", "console.toml"])
def test_fly_dockerfile_exists_relative_to_config(config_name):
    config_path = Path(__file__).resolve().parents[3] / "deploy" / "fly" / config_name
    config = tomllib.loads(config_path.read_text(encoding="utf-8"))

    assert (config_path.parent / config["build"]["dockerfile"]).is_file()
