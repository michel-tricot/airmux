from __future__ import annotations

from data_plane.config import load_config


def test_env_file_loaded_from_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("GW_BUNDLE_PUBLIC_KEY", raising=False)
    monkeypatch.delenv("GW_CACHE_DIR", raising=False)
    (tmp_path / ".env").write_text("GW_BUNDLE_PUBLIC_KEY=from-dotenv\nGW_CACHE_DIR=/var/cache/from-dotenv\n", encoding="utf-8")
    config = load_config()
    assert config.bundle_public_key_b64 == "from-dotenv"
    assert str(config.cache_dir) == "/var/cache/from-dotenv"


def test_console_env_wins_over_env_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GW_BUNDLE_PUBLIC_KEY", "from-console")
    (tmp_path / ".env").write_text("GW_BUNDLE_PUBLIC_KEY=from-dotenv\n", encoding="utf-8")
    assert load_config().bundle_public_key_b64 == "from-console"
