"""One module per provider, because no two listing endpoints agree on anything.

A generic normalizer looks tempting and quietly throws data away. Groq returns pricing,
modalities and a feature list; Anthropic returns a capabilities tree; OpenAI returns four
fields and a shutdown date. Flattening those through one code path means the catalog holds
the intersection of what every vendor publishes, which is almost nothing.

So each provider gets a module under sources/ that subclasses ModelSource, declares how to
reach its catalog, and maps its own fields by hand. Add a provider by adding a module.
Nothing else changes: the registry is a subclass walk, not a list to edit.

Write the module's docstring for the next person. It is the right home for the per-provider
instructions that used to live in nobody's head: which endpoint is the real catalog, what
"serverless" means for that vendor, which fields lie, what the account has to look like.
"""

from __future__ import annotations

import importlib
import json
import pkgutil
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar

from model_audit.catalog_tasks.http import fetch_bytes
from model_audit.catalog_tasks.types import integer, object_list, strings

if TYPE_CHECKING:
    from model_audit.catalog_ops import ProviderDefinition, SchemaDefinition
    from model_audit.catalog_tasks.types import CatalogObject, CatalogValue

UA = {"User-Agent": "tokkeeper-taxonomy/1.0", "Accept": "application/json"}


def per_mtok(value: CatalogValue) -> float | None:
    """Vendors quote per-token; the catalog stores per-million, rounded to the cent."""
    if value in (None, "", "0", 0):
        return 0.0 if value in ("0", 0) else None
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        return None
    try:
        return round(float(value) * 1_000_000, 4)
    except (TypeError, ValueError):
        return None


def required_openapi(definition: ProviderDefinition) -> str:
    if definition.openapi is None:
        message = f"{definition.id} has no OpenAPI source"
        raise ValueError(message)
    return definition.openapi


class ModelSource:
    """Base for a provider's model catalog.

    Subclasses set `provider_id` and `url`, then override `normalize`. Override `items` when the
    payload is not `{"data": [...]}`, and `fetch` when one request is not enough.
    """

    provider_id: str = ""
    url: str = ""
    auth: str = "bearer"  # "bearer", "header:<Name>", or "none"
    open_access: bool = False  # catalog readable without a credential
    definition: ProviderDefinition | None = None
    schemas: tuple[SchemaDefinition, ...] = ()
    documented_schemas: ClassVar[dict[str, CatalogObject]] = {}

    # ---- transport -------------------------------------------------------------

    def headers(self, key: str | None) -> dict[str, str]:
        head = dict(UA)
        if self.auth == "none" or not key:
            return head
        if self.auth.startswith("header:"):
            head[self.auth.split(":", 1)[1]] = key
        else:
            head["Authorization"] = f"Bearer {key}"
        return head

    def get(self, url: str, key: str | None) -> CatalogValue:
        return json.loads(fetch_bytes(url, self.headers(key), timeout=90))

    def fetch(self, key: str | None) -> CatalogValue:
        return self.get(self.url, key)

    # ---- shape -----------------------------------------------------------------

    def items(self, payload: CatalogValue) -> list[CatalogObject]:
        if isinstance(payload, list):
            return object_list(payload)
        if isinstance(payload, dict):
            for field in ("data", "models", "results", "items"):
                value = payload.get(field)
                if isinstance(value, list):
                    return object_list(value)
        return []

    def normalize(self, item: CatalogObject) -> CatalogObject | None:
        """Map one vendor record to a catalog record, or None to drop it.

        Return None for anything the account cannot call without provisioning: that is the
        whole point of the catalog, so a model in it is a model tokkeeper can route to today.
        """
        raise NotImplementedError

    def enrich(self, models: list[CatalogObject]) -> list[CatalogObject]:
        return models

    # ---- helpers for subclasses ------------------------------------------------

    @staticmethod
    def record(  # noqa: PLR0913 provider records enumerate independent catalog fields
        model_id: str,
        *,
        context_length: int | None = None,
        max_output_tokens: int | None = None,
        input_modalities: list[str] | None = None,
        output_modalities: list[str] | None = None,
        supports_tools: bool | None = None,
        supports_structured_output: bool | None = None,
        pricing: CatalogObject | None = None,
        **extra: CatalogValue,
    ) -> CatalogObject:
        out: CatalogObject = {
            "id": model_id,
            "context_length": context_length,
            "max_output_tokens": max_output_tokens,
            "input_modalities": input_modalities,
            "output_modalities": output_modalities,
            "supports_tools": supports_tools,
            "supports_structured_output": supports_structured_output,
            "pricing": pricing,
        }
        out.update({k: v for k, v in extra.items() if v not in (None, [], {})})
        return out

    @staticmethod
    def price(input_per_token: CatalogValue, output_per_token: CatalogValue, **rest: CatalogValue) -> CatalogObject | None:
        priced = {
            "input_per_mtok": per_mtok(input_per_token),
            "output_per_mtok": per_mtok(output_per_token),
        }
        priced.update({k: per_mtok(v) for k, v in rest.items() if per_mtok(v) is not None})
        return priced if any(v is not None for v in priced.values()) else None


class GenericModelSource(ModelSource):
    def normalize(self, item: CatalogObject) -> CatalogObject | None:
        model_id = item.get("id")
        if not isinstance(model_id, str) or not model_id:
            return None
        return self.record(
            model_id,
            context_length=integer(item.get("context_length")) or integer(item.get("context_window")),
            max_output_tokens=integer(item.get("max_output_tokens")) or integer(item.get("max_completion_tokens")),
            input_modalities=strings(item.get("input_modalities")) or None,
            output_modalities=strings(item.get("output_modalities")) or None,
            owned_by=item.get("owned_by"),
        )


def registry() -> dict[str, ModelSource]:
    """Every ModelSource subclass in this package, keyed by provider id."""
    package = Path(__file__).parent
    for module in pkgutil.iter_modules([str(package)]):
        if module.name != "base":
            importlib.import_module(f"{__package__}.{module.name}")

    found: dict[str, ModelSource] = {}
    pending = list(ModelSource.__subclasses__())
    while pending:
        cls = pending.pop()
        pending.extend(cls.__subclasses__())
        if cls.provider_id:
            found[cls.provider_id] = cls()
    return found
