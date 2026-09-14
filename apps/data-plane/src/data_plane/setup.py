from __future__ import annotations

import os
import secrets
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import yaml

from contract.taxonomy import parse_taxonomy
from data_plane.bundle.config import LocalBundleConfig
from data_plane.bundle.holder import BundleSet
from data_plane.bundle.local import LocalBundleSpec, compile_local, load_local
from data_plane.config import load_config

if TYPE_CHECKING:
    from pathlib import Path


def initialize(directory: Path, taxonomy_path: Path) -> None:
    taxonomy = parse_taxonomy(taxonomy_path)
    key = f"sk-inf-{secrets.token_urlsafe(32)}"
    spec = LocalBundleSpec(keys=[key], taxonomy=taxonomy)
    BundleSet.from_bundles((compile_local(spec, taxonomy, spec.model_dump_json(), datetime.now(tz=UTC)),))
    directory.mkdir(mode=0o700)
    config = {
        "data_plane": {
            "bundle": {"kind": "local", "path": "bundle.yml"},
            "secrets": {"kind": "env"},
            "events": {"kind": "devnull"},
        }
    }
    bundle = {"keys": ["${env:TOKKEEPER_INFERENCE_KEY}"], "taxonomy": os.path.relpath(taxonomy_path.resolve(), directory.resolve())}
    for name, contents in (
        ("inference.key", key + "\n"),
        ("bundle.yml", yaml.safe_dump(bundle, sort_keys=False)),
        ("tokkeeper.yml", yaml.safe_dump(config, sort_keys=False)),
    ):
        with (directory / name).open("x", encoding="utf-8") as destination:
            destination.write(contents)
        (directory / name).chmod(0o600)


def validate_local(config_path: Path) -> None:
    config = load_config(config_path)
    if not isinstance(config.bundle, LocalBundleConfig):
        message = "validate requires a local bundle configuration"
        raise TypeError(message)
    BundleSet.from_bundles((load_local(config.bundle.path, datetime.now(tz=UTC)),))
