"""Anthropic.

/v1/models needs the x-api-key header and an anthropic-version header; a bearer token is
parsed but is for OAuth tokens, not API keys.

The listing carries max_input_tokens and max_tokens, so limits never need borrowing here.
It also carries a nested capabilities tree, which is the only place Anthropic publishes
tool and structured-output support in machine-readable form. Read it rather than assuming:
capability differs across the family.

Pricing is not on the API and is not hardcoded here. The source follows Anthropic's
official llms.txt index and extracts each current model page, including cache-read and
cache-write tiers. models.dev and OpenRouter fill only facts still absent after that pass.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from model_audit.catalog_ops import ProviderDefinition, SchemaDefinition
from model_audit.catalog_tasks.types import boolean, integer, object_or_empty, required_string
from model_audit.provider_docs import apply_documentation, fetch_text, fetch_texts, parse_anthropic_model

from .base import ModelSource

if TYPE_CHECKING:
    from model_audit.catalog_tasks.types import CatalogObject


class Anthropic(ModelSource):
    provider_id = "anthropic"
    url = "https://api.anthropic.com/v1/models"
    auth = "header:x-api-key"
    definition = ProviderDefinition(
        id=provider_id,
        name="Anthropic",
        homepage="https://www.anthropic.com",
        docs="https://platform.claude.com/docs",
        base_url="https://api.anthropic.com/v1",
        models_url=url,
        openapi="https://raw.githubusercontent.com/anthropics/anthropic-sdk-typescript/main/.stats.yml",
        ingress=("anthropic",),
        primary_surface="anthropic",
        auth=("header_key:x-api-key",),
        env_var="ANTHROPIC_API_KEY",
        icon_mono="anthropic",
        icon_color="anthropic",
    )
    schemas = (
        SchemaDefinition(
            surface="anthropic",
            url="https://storage.googleapis.com/stainless-sdk-openapi-specs/anthropic/anthropic-891ba7f96c3771e1e3ba6cb37fe8cb6d8615b8a06b6c435d9df66f4aad144bb4.yml",
            path_pattern=r"^/v1/messages$",
        ),
    )
    docs_index = "https://platform.claude.com/llms.txt"

    def headers(self, key: str | None) -> dict[str, str]:
        head = super().headers(key)
        head["anthropic-version"] = "2023-06-01"
        return head

    def normalize(self, item: CatalogObject) -> CatalogObject:
        caps = object_or_empty(item.get("capabilities"))

        def supported(name: str) -> bool:
            return boolean(object_or_empty(caps.get(name)).get("supported")) is True

        inputs = ["text"]
        if supported("image_input"):
            inputs.append("image")
        if supported("pdf_input"):
            inputs.append("pdf")
        return self.record(
            required_string(item.get("id"), "Anthropic model id"),
            context_length=integer(item.get("max_input_tokens")),
            max_output_tokens=integer(item.get("max_tokens")),
            input_modalities=inputs,
            output_modalities=["text"],
            supports_tools=supported("code_execution") or bool(caps),
            supports_structured_output=supported("structured_outputs"),
            display_name=item.get("display_name"),
            supports_thinking=supported("thinking"),
            supports_batch=supported("batch"),
        )

    def enrich(self, models: list[CatalogObject]) -> list[CatalogObject]:
        index = fetch_text(self.docs_index)
        urls = tuple(sorted(set(re.findall(r"https://platform\.claude\.com/docs/en/models/[^ )]+/overview\.md", index))))
        documents = tuple(parse_anthropic_model(markdown, url) for url, markdown in fetch_texts(urls).items())
        return apply_documentation(models, documents)
