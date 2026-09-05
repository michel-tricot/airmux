from __future__ import annotations

import pytest

from contract import UnknownVarError, UnsupportedRefSchemeError, load_config_section, resolve_ref, try_resolve_ref


def _write_config(tmp_path, text):
    path = tmp_path / "airllm.yml"
    path.write_text(text, encoding="utf-8")
    return path


def test_resolve_ref_reads_env(monkeypatch):
    monkeypatch.setenv("REFS_TEST_KEY", "s3cr3t")
    assert resolve_ref("env:REFS_TEST_KEY") == "s3cr3t"


def test_resolve_ref_reads_file_and_strips(tmp_path):
    secret = tmp_path / "secret.txt"
    secret.write_text("s3cr3t\n", encoding="utf-8")
    assert resolve_ref(f"file:{secret}") == "s3cr3t"


def test_resolve_ref_rejects_unknown_scheme():
    with pytest.raises(UnsupportedRefSchemeError):
        resolve_ref("vault:whatever")


def test_try_resolve_ref_returns_none_for_missing_values(monkeypatch, tmp_path):
    monkeypatch.delenv("REFS_TEST_MISSING", raising=False)
    assert try_resolve_ref("env:REFS_TEST_MISSING") is None
    assert try_resolve_ref(f"file:{tmp_path}/absent.txt") is None


def test_load_config_section_interpolates_embedded_refs(tmp_path, monkeypatch):
    path = _write_config(tmp_path, "app:\n  database:\n    url: postgresql://${env:REFS_DB_USER}:${env:REFS_DB_PASSWORD}@db.internal:5432/app\n")
    monkeypatch.setenv("REFS_DB_USER", "alice")
    monkeypatch.setenv("REFS_DB_PASSWORD", "s3cr3t")
    section = load_config_section("app", path)
    assert section["database"]["url"] == "postgresql://alice:s3cr3t@db.internal:5432/app"


def test_embedded_file_refs_interpolate(tmp_path, monkeypatch):
    secret = tmp_path / "password.txt"
    secret.write_text("s3cr3t\n", encoding="utf-8")
    path = _write_config(tmp_path, f"app:\n  url: postgresql://alice:${{file:{secret}}}@db.internal:5432/app\n")
    assert load_config_section("app", path)["url"] == "postgresql://alice:s3cr3t@db.internal:5432/app"


def test_missing_embedded_ref_voids_the_whole_string(tmp_path, monkeypatch):
    path = _write_config(tmp_path, "app:\n  token: ${env:REFS_TEST_ABSENT}-suffix\n")
    monkeypatch.delenv("REFS_TEST_ABSENT", raising=False)
    assert load_config_section("app", path)["token"] is None


def test_whole_string_refs_keep_working(tmp_path, monkeypatch):
    monkeypatch.setenv("REFS_TEST_TOKEN", "tok")
    path = _write_config(tmp_path, "app:\n  token: env:REFS_TEST_TOKEN\n")
    assert load_config_section("app", path)["token"] == "tok"


def test_strings_without_known_ref_schemes_pass_through(tmp_path):
    path = _write_config(tmp_path, 'app:\n  greeting: "hello ${vault:secret}"\n')
    assert load_config_section("app", path)["greeting"] == "hello ${vault:secret}"


def test_env_refs_resolve_from_dotenv_next_to_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("REFS_DOTENV_TOKEN", raising=False)
    (tmp_path / ".env").write_text("REFS_DOTENV_TOKEN=from-dotenv\n", encoding="utf-8")
    path = _write_config(tmp_path, "app:\n  token: env:REFS_DOTENV_TOKEN\n")
    assert load_config_section("app", path)["token"] == "from-dotenv"


def test_console_env_wins_over_dotenv(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("REFS_DOTENV_PRIO=from-dotenv\n", encoding="utf-8")
    monkeypatch.setenv("REFS_DOTENV_PRIO", "from-console")
    path = _write_config(tmp_path, "app:\n  token: env:REFS_DOTENV_PRIO\n")
    assert load_config_section("app", path)["token"] == "from-console"


def test_gw_config_selects_the_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    path = tmp_path / "other.yml"
    path.write_text("app:\n  a: 1\n", encoding="utf-8")
    monkeypatch.setenv("AIRLLM_CONFIG", str(path))
    assert load_config_section("app") == {"a": 1}


def test_load_config_section_takes_only_the_named_section(tmp_path):
    path = _write_config(tmp_path, "app:\n  a: 1\nother:\n  b: 2\n")
    assert load_config_section("app", path) == {"a": 1}


def test_load_config_section_missing_file_or_section_is_empty(tmp_path):
    assert load_config_section("app", tmp_path / "absent.yml") == {}
    path = _write_config(tmp_path, "other:\n  b: 2\n")
    assert load_config_section("app", path) == {}


def test_a_ref_falls_back_to_its_default(tmp_path, monkeypatch):
    monkeypatch.delenv("REFS_TEST_DEFAULTED", raising=False)
    assert try_resolve_ref("env:REFS_TEST_DEFAULTED:-fallback") == "fallback"
    assert resolve_ref("env:REFS_TEST_DEFAULTED:-fallback") == "fallback"


def test_a_present_value_wins_over_the_default(monkeypatch):
    monkeypatch.setenv("REFS_TEST_DEFAULTED", "real")
    assert try_resolve_ref("env:REFS_TEST_DEFAULTED:-fallback") == "real"


def test_a_missing_file_falls_back_to_its_default(tmp_path):
    assert try_resolve_ref(f"file:{tmp_path}/absent.txt:-fallback") == "fallback"


def test_an_empty_default_resolves_to_the_empty_string(monkeypatch):
    """Shell semantics: the separator being present is what makes a value, even an empty one."""
    monkeypatch.delenv("REFS_TEST_DEFAULTED", raising=False)
    assert try_resolve_ref("env:REFS_TEST_DEFAULTED:-") == ""


def test_a_default_carries_through_interpolation(tmp_path, monkeypatch):
    monkeypatch.delenv("REFS_TEST_DEFAULTED", raising=False)
    path = _write_config(tmp_path, "app:\n  url: ${env:REFS_TEST_DEFAULTED:-postgresql://localhost:5432/app}\n")
    assert load_config_section("app", path)["url"] == "postgresql://localhost:5432/app"


def test_a_default_can_sit_beside_other_text(tmp_path, monkeypatch):
    monkeypatch.delenv("REFS_TEST_DEFAULTED", raising=False)
    path = _write_config(tmp_path, "app:\n  token: ${env:REFS_TEST_DEFAULTED:-anon}-suffix\n")
    assert load_config_section("app", path)["token"] == "anon-suffix"


def test_a_ref_without_a_default_still_voids_the_string(tmp_path, monkeypatch):
    """The forgiving default is opt-in; a bare ref that resolves to nothing keeps voiding its string."""
    monkeypatch.delenv("REFS_TEST_ABSENT", raising=False)
    path = _write_config(tmp_path, "app:\n  token: ${env:REFS_TEST_ABSENT}-suffix\n")
    assert load_config_section("app", path)["token"] is None


def test_vars_substitute_inside_refs_and_as_plain_values(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "keys").mkdir()
    (tmp_path / "keys" / "dataplane.key").write_text("sekrit\n", encoding="utf-8")
    path = tmp_path / "config.yml"
    path.write_text(
        "vars:\n  dir: keys\napp:\n  token: ${file:${var:dir}/dataplane.key}\n  cache_dir: ${var:dir}\n",
        encoding="utf-8",
    )
    section = load_config_section("app", path)
    assert section["token"] == "sekrit"
    assert section["cache_dir"] == "keys"


def test_an_unknown_var_fails_loudly(tmp_path):
    path = tmp_path / "config.yml"
    path.write_text("app:\n  cache_dir: ${var:missing}\n", encoding="utf-8")
    with pytest.raises(UnknownVarError):
        load_config_section("app", path)
