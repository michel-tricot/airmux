"""Azure OpenAI's OpenAI-compatible v1 endpoint.

The resource URL is a template because each account has its own hostname. The model field
is a deployment name, so this source only enriches a deployment named `gpt-4.1`; other
deployment names cannot be mapped to a base model without resource metadata.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from model_audit.catalog_ops import ProviderDefinition, SchemaDefinition

from .base import ModelSource, required_openapi

if TYPE_CHECKING:
    from model_audit.catalog_tasks.types import CatalogObject


class AzureOpenAI(ModelSource):
    provider_id = "azure-openai"
    url = "https://RESOURCE.openai.azure.com/openai/v1/models"
    definition = ProviderDefinition(
        id=provider_id,
        name="Azure OpenAI",
        homepage="https://azure.microsoft.com/en-us/products/ai-services/openai-service",
        docs="https://learn.microsoft.com/en-us/rest/api/microsoft-foundry/azureopenai/chat",
        base_url="https://RESOURCE.openai.azure.com/openai/v1",
        models_url=url,
        openapi="https://raw.githubusercontent.com/openai/openai-openapi/master/openapi.yaml",
        ingress=("oai",),
        primary_surface="oai",
        egress_kind="azure_openai",
        auth=("header_key:api-key",),
        env_var="AZURE_OPENAI_API_KEY",
        icon_mono="azure-openai",
    )
    schemas = (SchemaDefinition(surface="oai", url=required_openapi(definition), path_pattern=r"^/chat/completions$"),)

    def normalize(self, item: CatalogObject) -> CatalogObject | None:
        model_id = item.get("id")
        if not isinstance(model_id, str) or model_id != "gpt-4.1":
            return None
        return self.record(
            model_id,
            context_length=300_000,
            max_output_tokens=32_768,
            input_modalities=["text", "image"],
            output_modalities=["text"],
        )
