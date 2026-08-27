from __future__ import annotations

import json
import subprocess
import sys
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Literal, cast

import yaml
from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator

if TYPE_CHECKING:
    from pathlib import Path


class ProviderDefinition(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]*$")
    name: str
    homepage: HttpUrl
    docs: HttpUrl
    base_url: HttpUrl
    models_url: HttpUrl
    openapi: HttpUrl | None = None
    ingress: tuple[Literal["oai", "oai_responses", "anthropic", "google", "other_standard", "custom"], ...]
    auth: tuple[str, ...]
    env_var: str = Field(pattern=r"^[A-Z][A-Z0-9_]+$")
    icon_mono: str | None = None
    icon_color: str | None = None


class ModelDefinition(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    source: str
    context_window: int | None = Field(None, ge=1)
    max_output_tokens: int | None = Field(None, ge=1)

    @model_validator(mode="after")
    def complete_limits(self) -> ModelDefinition:
        if (self.context_window is None) != (self.max_output_tokens is None):
            message = "context_window and max_output_tokens must be supplied together"
            raise ValueError(message)
        return self


def run_catalog_script(root: Path, script: str, *arguments: str) -> subprocess.CompletedProcess[str]:
    path = root / "model-audit" / "catalog" / "scripts" / script
    return subprocess.run(  # noqa: S603 repository-owned catalog scripts are selected by the CLI
        [sys.executable, str(path), *arguments], cwd=root, capture_output=True, text=True, check=False
    )


def _provider_entry(definition: ProviderDefinition) -> dict[str, object]:
    icon_mono = definition.icon_mono or definition.id
    return {
        "id": definition.id,
        "name": definition.name,
        "icon_mono": icon_mono,
        "icon_color": definition.icon_color or icon_mono,
        "homepage": str(definition.homepage),
        "docs": str(definition.docs),
        "base_url": str(definition.base_url),
        "openapi": str(definition.openapi) if definition.openapi is not None else None,
        "models_url": str(definition.models_url),
        "ingress": list(definition.ingress),
        "auth": list(definition.auth),
        "env_var": definition.env_var,
        "schema": None,
    }


def _monogram(name: str) -> str:
    letter = next((character.upper() for character in name if character.isalnum()), "A")
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none">'
        '<rect width="24" height="24" rx="6" fill="currentColor"/>'
        f'<text x="12" y="16" text-anchor="middle" font-family="sans-serif" font-size="12" fill="white">{letter}</text></svg>\n'
    )


def add_provider(root: Path, definition_path: Path, *, replace: bool = False) -> ProviderDefinition:
    definition = ProviderDefinition.model_validate(yaml.safe_load(definition_path.read_text(encoding="utf-8")))
    taxonomy = root / "taxonomy"
    providers_path = taxonomy / "providers.yml"
    document = yaml.safe_load(providers_path.read_text(encoding="utf-8")) or {"providers": []}
    existing = next((provider for provider in document["providers"] if provider["id"] == definition.id), None)
    if existing is not None and not replace:
        message = f"provider {definition.id} already exists; pass --replace to update it"
        raise ValueError(message)
    providers = [provider for provider in document["providers"] if provider["id"] != definition.id]
    providers.append(_provider_entry(definition))
    providers.sort(key=lambda provider: provider["id"])
    providers_path.write_text(yaml.safe_dump({"providers": providers}, sort_keys=False, width=150, allow_unicode=True), encoding="utf-8")
    icon = taxonomy / "icons" / f"{definition.icon_mono or definition.id}.svg"
    if not icon.exists():
        icon.write_text(_monogram(definition.name), encoding="utf-8")
    result = run_catalog_script(root, "make_seed.py")
    if result.returncode != 0:
        message = result.stderr or result.stdout
        raise RuntimeError(message.strip())
    return definition


def add_model(root: Path, provider_id: str, definition: ModelDefinition, *, replace: bool = False) -> Path:
    providers_path = root / "taxonomy" / "providers.yml"
    providers = yaml.safe_load(providers_path.read_text(encoding="utf-8"))["providers"]
    if provider_id not in {provider["id"] for provider in providers}:
        message = f"provider {provider_id} is not in providers.yml"
        raise ValueError(message)
    path = root / "taxonomy" / "models" / f"{provider_id}.json"
    document: dict[str, object]
    if path.exists():
        document = cast("dict[str, object]", json.loads(path.read_text(encoding="utf-8")))
    else:
        document = {
            "provider": provider_id,
            "source": definition.source,
            "source_type": "docs",
            "updated": datetime.now(tz=UTC).date().isoformat(),
            "models": [],
        }
    model_values = document.get("models")
    existing = cast("list[object]", model_values) if isinstance(model_values, list) else []
    previous = next((cast("dict[str, object]", model) for model in existing if isinstance(model, dict) and model.get("id") == definition.id), None)
    if previous is not None and not replace:
        message = f"model {provider_id}/{definition.id} already exists; pass --replace to update it"
        raise ValueError(message)
    models = [cast("dict[str, object]", model) for model in existing if isinstance(model, dict) and model.get("id") != definition.id]
    model = {
        **(previous or {}),
        "id": definition.id,
        "kind": "text",
        "source": definition.source,
    }
    if definition.context_window is not None:
        model.update(
            {
                "context_length": definition.context_window,
                "max_output_tokens": definition.max_output_tokens,
                "limits_source": "vendor-docs",
            }
        )
    models.append(model)
    models.sort(key=lambda model: str(model.get("id")))
    document.setdefault("source", definition.source)
    document.setdefault("source_type", "docs")
    document["count"] = len(models)
    document["models"] = models
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    return path
