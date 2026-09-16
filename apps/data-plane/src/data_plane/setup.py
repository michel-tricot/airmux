from __future__ import annotations

import os
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime
from gzip import decompress
from importlib.resources import files
from typing import TYPE_CHECKING

import yaml

from contract import EnvStoreConfig, uuid7
from contract.initialization import GENERATED_STATE_GITIGNORE, write_new_configuration
from contract.taxonomy import TaxonomySpec, parse_taxonomy
from data_plane.bundle.config import LocalBundleConfig
from data_plane.bundle.holder import BundleSet
from data_plane.bundle.local import LocalBundleSpec, LocalKey, compile_local, load_local
from data_plane.config import load_config

if TYPE_CHECKING:
    from pathlib import Path


@dataclass(frozen=True)
class GatewayProviderGuide:
    provider_id: str
    configured_variable: str | None
    suggested_variable: str
    models: tuple[str, ...]


@dataclass(frozen=True)
class GatewayGuide:
    providers: tuple[GatewayProviderGuide, ...]


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
    user_id = uuid7()
    spec = LocalBundleSpec(keys=[LocalKey(token=key, user_id=user_id)], taxonomy=taxonomy)
    BundleSet.from_bundles((compile_local(spec, taxonomy, spec.model_dump_json(), datetime.now(tz=UTC)),))
    config = {
        "data_plane": {
            "bundle": {"kind": "local", "path": "bundle.yml"},
            "secrets": {"kind": "env"},
            "events": {"kind": "devnull"},
        }
    }
    bundle = {"keys": [{"token": "${file:inference.key}", "user_id": str(user_id)}], "taxonomy": taxonomy_reference}
    write_new_configuration(
        directory,
        {
            ".gitignore": GENERATED_STATE_GITIGNORE,
            "inference.key": key + "\n",
            "bundle.yml": yaml.safe_dump(bundle, sort_keys=False),
            "tokkeeper.yml": yaml.safe_dump(config, sort_keys=False),
            **taxonomy_file,
        },
    )


def _provider_guide(provider_id: str, variables: tuple[str, ...], models: tuple[str, ...]) -> GatewayProviderGuide:
    configured = next((variable for variable in variables if os.environ.get(variable)), None)
    return GatewayProviderGuide(
        provider_id=provider_id,
        configured_variable=configured,
        suggested_variable=configured or variables[-1],
        models=models,
    )


def describe_configuration(config_path: Path) -> GatewayGuide:
    config = load_config(config_path)
    if not isinstance(config.bundle, LocalBundleConfig) or not isinstance(config.secrets, EnvStoreConfig):
        message = "the standalone gateway guide requires a local bundle and environment secret store"
        raise TypeError(message)
    bundle = load_local(config.bundle.path, datetime.now(tz=UTC))
    secret_store = config.secrets.build()
    credentials = {credential.ref.service: credential for credential in bundle.catalog.credentials}
    return GatewayGuide(
        providers=tuple(
            _provider_guide(
                provider_id=provider.provider_id,
                variables=secret_store.variables_for(credentials[provider.provider_id].ref),
                models=tuple(model.model_id for model in bundle.catalog.models if model.provider_id == provider.provider_id),
            )
            for provider in bundle.catalog.providers
        )
    )


def validate_configuration(config_path: Path) -> None:
    config = load_config(config_path)
    if isinstance(config.bundle, LocalBundleConfig):
        BundleSet.from_bundles((load_local(config.bundle.path, datetime.now(tz=UTC)),))
