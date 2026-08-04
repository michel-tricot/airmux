from __future__ import annotations

import pytest
import typer

from cli.main import ModelCreate, ProviderCreate, _fill_spec


def test_flags_only_no_prompting(monkeypatch):
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    spec = _fill_spec(
        ProviderCreate,
        {"provider_id": "groq", "base_url": "https://api.groq.com/openai/v1", "credential_ref": "env:GROQ_API_KEY"},
    )
    assert spec.org_id == "org-dev"
    assert spec.kind == "openai_compatible"


def test_missing_required_without_tty_exits(monkeypatch):
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    with pytest.raises(typer.Exit):
        _fill_spec(ProviderCreate, {"provider_id": "groq"})


def test_prompts_fill_missing_fields(monkeypatch):
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    answers = iter(["m1", "p1", "", "0.5", "1.5", "64000", "streaming, tools, vision", "org-x"])
    monkeypatch.setattr(typer, "prompt", lambda label, default=None: next(answers) or default)
    spec = _fill_spec(ModelCreate, {})
    assert spec.model_id == "m1"
    assert spec.upstream_model == ""
    assert spec.input_price_per_mtok == 0.5
    assert spec.context_window == 64000
    assert spec.capabilities == ["streaming", "tools", "vision"]
    assert spec.org_id == "org-x"


def test_invalid_value_exits_with_message(monkeypatch):
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    with pytest.raises(typer.Exit):
        _fill_spec(
            ProviderCreate,
            {"provider_id": "x", "base_url": "u", "credential_ref": "c", "kind": "not-a-kind"},
        )
