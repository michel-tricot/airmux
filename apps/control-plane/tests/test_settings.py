from __future__ import annotations

from control_plane.config import database_url, load_settings


def test_load_settings_resolves_refs(tmp_path, monkeypatch):
    (tmp_path / "bundle.key").write_text("bundle-key-from-file", encoding="utf-8")
    config = (
        "control_plane:\n"
        "  database:\n    url: sqlite+aiosqlite:///cp.db\n"
        "  auth:\n    token_signing_key: env:TEST_TOKEN_KEY\n"
        f"  bundle:\n    signing_key: file:{tmp_path}/bundle.key\n"
    )
    (tmp_path / "airllm.yml").write_text(config, encoding="utf-8")
    monkeypatch.setenv("GW_CONFIG", str(tmp_path / "airllm.yml"))
    monkeypatch.setenv("TEST_TOKEN_KEY", "token-key-from-env")

    settings = load_settings()
    assert settings.database.url == "sqlite+aiosqlite:///cp.db"
    assert settings.auth.token_signing_key == "token-key-from-env"
    assert settings.bundle.signing_key == "bundle-key-from-file"
    assert settings.dev is False


def test_dev_flag_comes_from_the_environment(tmp_path, monkeypatch):
    (tmp_path / "airllm.yml").write_text('control_plane:\n  auth:\n    token_signing_key: "k"\n  bundle:\n    signing_key: "k"\n', encoding="utf-8")
    monkeypatch.setenv("GW_CONFIG", str(tmp_path / "airllm.yml"))
    monkeypatch.setenv("GW_DEV", "1")
    assert load_settings().dev is True


def test_database_url_falls_back_without_a_config_file(tmp_path, monkeypatch):
    monkeypatch.setenv("GW_CONFIG", str(tmp_path / "missing.yml"))
    assert database_url() == "sqlite+aiosqlite:///airllm.db"
