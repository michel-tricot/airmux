from __future__ import annotations

import os

import pytest

from airmux_runtime.config import InvalidConfigReferenceError, MissingConfigReferenceError, load_config_section


def test_loader_resolves_only_whole_value_references(tmp_path, monkeypatch):
    monkeypatch.setenv("AIRMUX_TEST_VALUE", "resolved")
    path = tmp_path / "airmux.yml"
    path.write_text(
        "app:\n  value: ${env:AIRMUX_TEST_VALUE}\n  defaulted: ${env:AIRMUX_ABSENT:-fallback}\n  literal: prefix-${env:AIRMUX_TEST_VALUE}\n",
        encoding="utf-8",
    )

    with pytest.raises(InvalidConfigReferenceError, match="whole YAML value"):
        load_config_section("app", path)

    path.write_text("app:\n  value: ${env:AIRMUX_TEST_VALUE}\n  defaulted: ${env:AIRMUX_ABSENT:-fallback}\n", encoding="utf-8")
    assert load_config_section("app", path) == {"value": "resolved", "defaulted": "fallback"}


def test_loader_does_not_discover_dotenv_or_mutate_the_environment(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("AIRMUX_DOTENV_ONLY", raising=False)
    (tmp_path / ".env").write_text("AIRMUX_DOTENV_ONLY=private\n", encoding="utf-8")
    path = tmp_path / "airmux.yml"
    path.write_text("app:\n  value: ${env:AIRMUX_DOTENV_ONLY}\n", encoding="utf-8")
    before = dict(os.environ)

    with pytest.raises(MissingConfigReferenceError, match="AIRMUX_DOTENV_ONLY"):
        load_config_section("app", path)

    assert dict(os.environ) == before


def test_loader_rejects_missing_files_sections_and_references(tmp_path, monkeypatch):
    with pytest.raises(FileNotFoundError):
        load_config_section("app", tmp_path / "missing.yml")

    path = tmp_path / "airmux.yml"
    path.write_text("other: {}\n", encoding="utf-8")
    with pytest.raises(TypeError, match="app section"):
        load_config_section("app", path)

    monkeypatch.delenv("AIRMUX_MISSING", raising=False)
    path.write_text("app:\n  value: ${env:AIRMUX_MISSING}\n", encoding="utf-8")
    with pytest.raises(MissingConfigReferenceError, match="AIRMUX_MISSING"):
        load_config_section("app", path)
