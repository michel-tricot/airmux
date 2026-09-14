"""OpenAI.

/v1/models is deliberately bare: id, created, owned_by and shutdown_date. The source
discovers every official model Markdown page from OpenAI's all-model index and extracts
limits, modalities, pricing, snapshots, and declared features before secondary enrichment.

Do not hardcode a price table here. Official pages are reacquired on every sync and retain
their documentation URL. models.dev and OpenRouter fill only API-listed models absent from
the official index.

Do not try to infer limits from the model id. The names encode marketing tiers, not
context windows, and the mapping has broken at every generation.

shutdown_date is worth carrying: it is the only machine-readable deprecation signal any
provider in the catalog publishes.

The API-listed gpt-3.5-turbo-16k and gpt-5-search-api aliases have no exact current model
page. Minimal Chat Completions calls verified text input and text output for both aliases and
their returned snapshots. The 16k alias also inherits the current gpt-3.5-turbo page because
the provider resolves it to that documented family.
"""

from __future__ import annotations

import re
from dataclasses import replace
from typing import TYPE_CHECKING
from urllib.parse import urljoin

from model_audit.catalog_ops import ProviderDefinition, SchemaDefinition
from model_audit.catalog_tasks.types import required_string
from model_audit.provider_docs import apply_documentation, fetch_text, fetch_texts, parse_openai_model, parse_openai_pricing

from .base import ModelSource, required_openapi

if TYPE_CHECKING:
    from typing import ClassVar

    from model_audit.catalog_tasks.types import CatalogObject


class OpenAI(ModelSource):
    provider_id = "openai"
    url = "https://api.openai.com/v1/models"
    definition = ProviderDefinition(
        id=provider_id,
        name="OpenAI",
        homepage="https://openai.com",
        docs="https://platform.openai.com/docs",
        base_url="https://api.openai.com/v1",
        models_url=url,
        openapi="https://raw.githubusercontent.com/openai/openai-openapi/master/openapi.yaml",
        ingress=("oai", "oai_responses"),
        primary_surface="oai",
        auth=("bearer",),
        env_var="OPENAI_API_KEY",
        icon_mono="openai",
        icon_color="openai",
    )
    schemas = (
        SchemaDefinition(surface="oai", url=required_openapi(definition), path_pattern=r"^/chat/completions$"),
        SchemaDefinition(surface="oai_responses", url=required_openapi(definition), path_pattern=r"^/responses$"),
    )
    docs_catalog = "https://developers.openai.com/api/docs/models/all.md"
    docs_pricing = "https://developers.openai.com/api/docs/pricing.md"
    verified_text_models = frozenset({"gpt-3.5-turbo-16k", "gpt-5-search-api", "gpt-5-search-api-2025-10-14"})
    documented_aliases: ClassVar[dict[str, tuple[str, ...]]] = {"gpt-3.5-turbo": ("gpt-3.5-turbo-16k",)}

    def normalize(self, item: CatalogObject) -> CatalogObject:
        model_id = required_string(item.get("id"), "OpenAI model id")
        modalities = ["text"] if model_id in self.verified_text_models else None
        return self.record(model_id, input_modalities=modalities, output_modalities=modalities, shutdown_date=item.get("shutdown_date"))

    def enrich(self, models: list[CatalogObject]) -> list[CatalogObject]:
        catalog = fetch_text(self.docs_catalog)
        paths = tuple(sorted(set(re.findall(r"\((/api/docs/models/[^)]+\.md)\)", catalog)) - {"/api/docs/models/all.md"}))
        urls = tuple(urljoin(self.docs_catalog, path) for path in paths)
        model_documents = tuple(parse_openai_model(markdown, url) for url, markdown in fetch_texts(urls).items())
        model_documents = tuple(
            replace(document, ids=(*document.ids, *self.documented_aliases.get(document.ids[0], ()))) for document in model_documents
        )
        documents = (
            *parse_openai_pricing(fetch_text(self.docs_pricing), self.docs_pricing),
            *model_documents,
        )
        return apply_documentation(models, documents)
