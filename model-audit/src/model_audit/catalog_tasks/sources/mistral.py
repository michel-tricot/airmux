"""Mistral.

The API model card carries limits, a capability map, aliases and a deprecation date, but no
pricing. The source discovers Mistral's official model pages and extracts token-denominated
rates and context limits. Mixed-unit entries such as audio per minute are not mislabeled as
per-million-token prices. Secondary catalogs fill only remaining gaps.

**capabilities.completion_chat is the membership filter.** One listing carries chat models
alongside OCR, moderation, classification, embedding and audio models, and the ids do not
say which is which. model_kind would drop some of them later, but the vendor's own flag is
the reliable signal and it is applied here.

**Fine-tuned models are excluded.** The item is a oneOf discriminated on `type`, base or
fine-tuned, and a fine-tuned model exists only for the account that trained it. Including
them would let account state leak into a catalog that is meant to describe the provider, and
the entry would be unroutable for anyone else. `archived` appears only on that variant.

Aliases are kept but never used as the id: mistral-large-latest follows whichever dated
build is current, and a key that silently repoints is not a routing key.

**There is no /v1/messages route, whatever the status codes suggest.** With a bad key it
answers 401 while /v1/messages-xyz and /v1/chat answer 404, which reads as routing before
auth and therefore as a real endpoint. It is not: with a valid key the same request returns
404 "Not found". Mistral is oai only.

Treat a 401 on this host as no evidence either way. Only an authenticated request separates
a route that exists from one that does not.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from model_audit.catalog_ops import ProviderDefinition, SchemaDefinition
from model_audit.catalog_tasks.types import boolean, integer, object_or_empty, required_string, strings
from model_audit.provider_docs import apply_documentation, fetch_text, fetch_texts, parse_mistral_index, parse_mistral_model

from .base import ModelSource, required_openapi

if TYPE_CHECKING:
    from model_audit.catalog_tasks.types import CatalogObject


class Mistral(ModelSource):
    provider_id = "mistral"
    url = "https://api.mistral.ai/v1/models"
    docs_catalog = "https://docs.mistral.ai/models"
    definition = ProviderDefinition(
        id=provider_id,
        name="Mistral AI",
        homepage="https://mistral.ai",
        docs="https://docs.mistral.ai",
        base_url="https://api.mistral.ai/v1",
        models_url=url,
        openapi="https://raw.githubusercontent.com/mistralai/platform-docs-public/main/openapi.yaml",
        ingress=("oai",),
        primary_surface="oai",
        auth=("bearer",),
        env_var="MISTRAL_API_KEY",
        icon_mono="mistral",
        icon_color="mistral-color",
    )
    schemas = (SchemaDefinition(surface="oai", url=required_openapi(definition), path_pattern=r"^/v1/chat/completions$"),)

    def normalize(self, item: CatalogObject) -> CatalogObject | None:
        # a fine-tune belongs to one account, not to the provider's catalog
        if item.get("type") == "fine-tuned":
            return None
        capabilities = object_or_empty(item.get("capabilities"))
        if boolean(capabilities.get("completion_chat")) is not True:
            return None

        return self.record(
            required_string(item.get("id"), "Mistral model id"),
            context_length=integer(item.get("max_context_length")),
            input_modalities=["text", "image"] if capabilities.get("vision") else ["text"],
            output_modalities=["text"],
            supports_tools=boolean(capabilities.get("function_calling")),
            pricing=None,  # published on the pricing page only
            display_name=item.get("name"),
            aliases=sorted(strings(item.get("aliases"))),
            deprecation_date=item.get("deprecation"),
            deprecation_replacement=item.get("deprecation_replacement_model"),
            default_temperature=item.get("default_model_temperature"),
        )

    def enrich(self, models: list[CatalogObject]) -> list[CatalogObject]:
        urls = parse_mistral_index(fetch_text(self.docs_catalog), self.docs_catalog)
        documents = tuple(parse_mistral_model(document, url) for url, document in fetch_texts(urls).items() if "Click to copy:" in document)
        return apply_documentation(models, documents)
