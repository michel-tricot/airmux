from __future__ import annotations

from pathlib import Path

import yaml

from control_plane.setup import DEFAULT_CONFIG_YML


def test_default_config_matches_repo_airllm_yml():
    rendered = yaml.safe_load(
        DEFAULT_CONFIG_YML.format(
            db_url="sqlite+aiosqlite:///airllm.db",
            control_plane_url="http://127.0.0.1:8000",
            org="org-dev",
            cache_dir=".airllm",
        )
    )
    repo = yaml.safe_load((Path(__file__).parents[3] / "airllm.yml").read_text(encoding="utf-8"))
    assert rendered == repo
