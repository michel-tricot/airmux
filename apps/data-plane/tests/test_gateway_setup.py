from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError
from typer.testing import CliRunner

from cli.gateway import gateway_app as app
from data_plane.bundle import BundleHolder, LocalBundleConfig
from data_plane.bundle.local import LOCAL_ORG, LocalBundleSource, load_local
from data_plane.config import load_config
from data_plane.setup import describe_configuration, initialize

TAXONOMY = {
    "providers": [{"provider_id": "stub", "kind": "openai_compatible", "base_url": "http://localhost:9000", "icon": ""}],
    "models": [{"model_id": "echo", "provider_id": "stub", "input_modalities": ["text"], "output_modalities": ["text"]}],
}


def write_taxonomy(tmp_path):
    path = tmp_path / "taxonomy.yml"
    path.write_text(yaml.safe_dump(TAXONOMY))
    return path


def test_external_taxonomy_reloads_and_keeps_last_good_snapshot(tmp_path, monkeypatch):
    taxonomy = write_taxonomy(tmp_path)
    bundle = tmp_path / "bundle.yml"
    bundle.write_text("keys: ['${env:TOKKEEPER_INFERENCE_KEY}']\ntaxonomy: taxonomy.yml\n")
    monkeypatch.setenv("TOKKEEPER_INFERENCE_KEY", "sk-inf-private")
    monkeypatch.chdir(tmp_path.parent)
    holder = BundleHolder()
    source = LocalBundleSource(LocalBundleConfig(kind="local", path=bundle), holder)
    source.load()
    initial = holder.current.snapshots[LOCAL_ORG]
    assert initial.bundle.catalog.models[0].upstream_model == "echo"
    assert "sk-inf-private" not in initial.bundle.model_dump_json()
    source.load()
    assert holder.current.snapshots[LOCAL_ORG] is initial
    timestamp = taxonomy.stat()
    taxonomy.write_text(taxonomy.read_text().replace("model_id: echo", "model_id: next"))
    os.utime(taxonomy, ns=(timestamp.st_atime_ns, timestamp.st_mtime_ns))
    source.load()
    updated = holder.current.snapshots[LOCAL_ORG]
    assert updated.bundle.bundle_id != initial.bundle.bundle_id
    assert "next" in updated.model_index
    taxonomy.write_text("models: [{model_id: broken}]\n")
    with pytest.raises(ValidationError):
        source.load()
    assert holder.current.snapshots[LOCAL_ORG] is updated
    taxonomy.unlink()
    with pytest.raises(FileNotFoundError):
        source.load()
    assert holder.current.snapshots[LOCAL_ORG] is updated
    write_taxonomy(tmp_path)
    source.load()
    assert "echo" in holder.current.snapshots[LOCAL_ORG].model_index


@pytest.mark.parametrize("keys", [[], [""], ["wrong-prefix"], ["sk-inf-duplicate", "sk-inf-duplicate"], ["${env:MISSING_GATEWAY_KEY}"]])
def test_local_keys_reject_unusable_or_duplicate_tokens(tmp_path, monkeypatch, keys):
    monkeypatch.delenv("MISSING_GATEWAY_KEY", raising=False)
    bundle = tmp_path / "bundle.yml"
    bundle.write_text(yaml.safe_dump({"keys": keys, "taxonomy": TAXONOMY}))
    with pytest.raises(ValidationError):
        load_local(bundle, datetime.now(tz=UTC))


def test_init_creates_private_files_and_validate_works_outside_the_directory(tmp_path, monkeypatch):
    taxonomy = write_taxonomy(tmp_path)
    directory = tmp_path / "gateway"
    runner = CliRunner()
    result = runner.invoke(app, ["init", "--directory", str(directory), "--taxonomy", str(taxonomy)])
    assert result.exit_code == 0, result.output
    key = (directory / "inference.key").read_text().strip()
    assert key.startswith("sk-inf-")
    assert len(key) >= 40
    assert key not in result.output
    assert (directory / "inference.key").stat().st_mode & 0o777 == 0o600
    assert directory.stat().st_mode & 0o777 == 0o700
    assert "providers:" not in (directory / "bundle.yml").read_text()
    assert not (directory / "taxonomy.yml").exists()
    monkeypatch.setenv("TOKKEEPER_CONFIG", str(directory / "tokkeeper.yml"))
    monkeypatch.chdir(tmp_path.parent)
    config = load_config()
    assert isinstance(config.bundle, LocalBundleConfig)
    assert config.bundle.path == directory / "bundle.yml"
    result = runner.invoke(app, ["validate", "--config", str(directory / "tokkeeper.yml")])
    assert result.exit_code == 0, result.output
    assert key not in result.output
    result = runner.invoke(app, ["init", "--directory", str(directory), "--taxonomy", str(taxonomy)])
    assert result.exit_code != 0
    assert (directory / "inference.key").read_text().strip() == key


def test_describe_configuration_includes_every_provider_and_model(tmp_path, monkeypatch):
    taxonomy = {
        "providers": [
            {"provider_id": "first", "base_url": "http://localhost:9000"},
            {"provider_id": "second", "base_url": "http://localhost:9001"},
        ],
        "models": [
            {"model_id": "first-a", "provider_id": "first", "input_modalities": ["text"], "output_modalities": ["text"]},
            {"model_id": "second-a", "provider_id": "second", "input_modalities": ["text"], "output_modalities": ["text"]},
            {"model_id": "first-b", "provider_id": "first", "input_modalities": ["text"], "output_modalities": ["text"]},
        ],
    }
    taxonomy_path = tmp_path / "taxonomy.yml"
    taxonomy_path.write_text(yaml.safe_dump(taxonomy))
    directory = tmp_path / "gateway"
    assert initialize(directory, taxonomy_path) is None
    monkeypatch.setenv("SECOND_API_KEY", "private-provider-key")
    guide = describe_configuration(directory / "tokkeeper.yml")
    assert [(provider.provider_id, provider.models) for provider in guide.providers] == [
        ("first", ("first-a", "first-b")),
        ("second", ("second-a",)),
    ]
    assert guide.providers[0].variables[-1] == "FIRST_API_KEY"
    assert guide.providers[0].configured_variable is None
    assert guide.providers[1].configured_variable == "SECOND_API_KEY"


def test_init_rejects_invalid_taxonomy_before_writing(tmp_path):
    taxonomy = tmp_path / "taxonomy.yml"
    taxonomy.write_text("models: [{model_id: incomplete}]\n")
    directory = tmp_path / "gateway"
    result = CliRunner().invoke(app, ["init", "--directory", str(directory), "--taxonomy", str(taxonomy)])
    assert result.exit_code != 0
    assert not directory.exists()


def test_init_copies_the_shipped_taxonomy_without_a_control_plane(tmp_path):
    directory = tmp_path / "gateway"
    result = CliRunner().invoke(app, ["init", "--directory", str(directory)])
    assert result.exit_code == 0, result.output
    taxonomy = directory / "taxonomy.yml"
    assert taxonomy.read_text(encoding="utf-8") == (Path(__file__).resolve().parents[3] / "taxonomy/taxonomy.yml").read_text(encoding="utf-8")
    assert yaml.safe_load((directory / "bundle.yml").read_text(encoding="utf-8"))["taxonomy"] == "taxonomy.yml"


@pytest.mark.parametrize(
    "taxonomy",
    [
        {**TAXONOMY, "providers": TAXONOMY["providers"] * 2},
        {**TAXONOMY, "models": [{**TAXONOMY["models"][0], "input_price_per_mtok": -1}]},
        {**TAXONOMY, "models": [{**TAXONOMY["models"][0], "provider_id": "unknown"}]},
        {**TAXONOMY, "providers": [{**TAXONOMY["providers"][0], "kind": "unregistered"}]},
        {**TAXONOMY, "providers": [{**TAXONOMY["providers"][0], "base_urll": "http://wrong.test"}]},
        {"providers": [], "models": []},
    ],
)
def test_init_rejects_unusable_taxonomy(tmp_path, taxonomy):
    path = tmp_path / "taxonomy.yml"
    path.write_text(yaml.safe_dump(taxonomy))
    directory = tmp_path / "gateway"
    result = CliRunner().invoke(app, ["init", "--directory", str(directory), "--taxonomy", str(path)])
    assert result.exit_code != 0
    assert not directory.exists()


def test_local_configuration_rejects_unknown_fields():
    with pytest.raises(ValidationError, match="reload_intervall"):
        LocalBundleConfig.model_validate({"kind": "local", "path": "bundle.yml", "reload_intervall": 1})


def test_validation_does_not_disclose_an_invalid_inference_key(tmp_path):
    directory = tmp_path / "gateway"
    taxonomy = write_taxonomy(tmp_path)
    runner = CliRunner()
    assert runner.invoke(app, ["init", "--directory", str(directory), "--taxonomy", str(taxonomy)]).exit_code == 0
    key = "private-but-invalid-token"
    (directory / "bundle.yml").write_text(yaml.safe_dump({"keys": [key], "taxonomy": str(taxonomy)}))
    result = runner.invoke(app, ["validate", "--config", str(directory / "tokkeeper.yml")])
    assert result.exit_code != 0
    assert key not in result.output
