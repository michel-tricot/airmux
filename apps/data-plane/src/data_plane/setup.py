from __future__ import annotations

import os
import secrets
from datetime import UTC, datetime
from gzip import decompress
from importlib.resources import files
from typing import TYPE_CHECKING

import yaml

from contract.initialization import write_new_configuration
from contract.taxonomy import TaxonomySpec, parse_taxonomy
from data_plane.bundle.config import LocalBundleConfig
from data_plane.bundle.holder import BundleSet
from data_plane.bundle.local import LocalBundleSpec, compile_local, load_local
from data_plane.config import load_config

if TYPE_CHECKING:
    from pathlib import Path


def initialize(directory: Path, taxonomy_path: Path | None = None) -> None:
    if taxonomy_path is None:
        taxonomy_text = decompress(files("data_plane").joinpath("resources", "taxonomy.yml.gz").read_bytes()).decode("utf-8")
        taxonomy = TaxonomySpec.model_validate(yaml.safe_load(taxonomy_text))
        taxonomy_reference = "taxonomy.yml"
        taxonomy_file = {taxonomy_reference: taxonomy_text}
    else:
        taxonomy = parse_taxonomy(taxonomy_path)
        taxonomy_reference = os.path.relpath(taxonomy_path.resolve(), directory.resolve())
        taxonomy_file = {}
    key = f"sk-inf-{secrets.token_urlsafe(32)}"
    spec = LocalBundleSpec(keys=[key], taxonomy=taxonomy)
    BundleSet.from_bundles((compile_local(spec, taxonomy, spec.model_dump_json(), datetime.now(tz=UTC)),))
    config = {
        "data_plane": {
            "bundle": {"kind": "local", "path": "bundle.yml"},
            "secrets": {"kind": "env"},
            "events": {"kind": "devnull"},
        }
    }
    bundle = {"keys": ["${file:.tokkeeper/inference.key}"], "taxonomy": taxonomy_reference}
    write_new_configuration(
        directory,
        {
            ".tokkeeper/inference.key": key + "\n",
            "bundle.yml": yaml.safe_dump(bundle, sort_keys=False),
            "tokkeeper.yml": yaml.safe_dump(config, sort_keys=False),
            **taxonomy_file,
        },
    )


def validate_configuration(config_path: Path) -> None:
    config = load_config(config_path)
    if isinstance(config.bundle, LocalBundleConfig):
        BundleSet.from_bundles((load_local(config.bundle.path, datetime.now(tz=UTC)),))
