"""Cerebras.

**The documented endpoint needs a key; the useful one does not.** /v1/models answers 403
without a credential, while /public/v1/models is open and returns strictly more per model.
Both are in the vendor's spec and only the authenticated one looks canonical, so the open
catalog is easy to miss.

That open payload is the richest in this catalog: per-token pricing, a capabilities map, a
supported_parameters map, architecture and modality, context and completion limits,
quantization, and deprecated and preview flags. Nothing else here publishes the parameter
list a model accepts as data rather than prose.

Prices are per-token decimal strings, like Groq's, so the shared per_mtok conversion is
correct and no local scaling is needed.

The catalog is small and deliberately so: two models, which models.dev independently agrees
on. Do not read that as a fetch failure. Checked with a real key: the authenticated endpoint
lists exactly the same two ids, so the open one is complete as well as richer, and nothing
is gained by spending a credential on the other.

`preview` marks a model as available but not yet stable, and `deprecated` marks one on the
way out. Both are carried rather than filtered: both are callable today, which is the
question the catalog answers, and a router wants to see the flag rather than have the row
disappear.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from model_audit.catalog_ops import ProviderDefinition, SchemaDefinition
from model_audit.catalog_tasks.types import boolean, integer, object_or_empty, required_string, string

from .base import ModelSource, required_openapi

if TYPE_CHECKING:
    from model_audit.catalog_tasks.types import CatalogObject


class Cerebras(ModelSource):
    provider_id = "cerebras"
    # the authenticated /v1/models 403s and carries less; see the docstring
    url = "https://api.cerebras.ai/public/v1/models"
    open_access = True
    definition = ProviderDefinition(
        id=provider_id,
        name="Cerebras",
        homepage="https://cerebras.ai",
        docs="https://inference-docs.cerebras.ai",
        base_url="https://api.cerebras.ai/v1",
        models_url=url,
        openapi="https://storage.googleapis.com/stainless-sdk-openapi-specs/cerebras/cerebras-cloud-5471bd6d34fdddff21977458788b979ce93f6b080e11ff0d35777182b6615baa.yml",
        ingress=("oai",),
        primary_surface="oai",
        auth=("bearer",),
        env_var="CEREBRAS_API_KEY",
        icon_mono="cerebras",
        icon_color="cerebras-color",
    )
    schemas = (SchemaDefinition(surface="oai", url=required_openapi(definition), path_pattern=r"chat/completions$"),)

    def normalize(self, item: CatalogObject) -> CatalogObject:
        limits = object_or_empty(item.get("limits"))
        capabilities = object_or_empty(item.get("capabilities"))
        architecture = object_or_empty(item.get("architecture"))
        modality = string(architecture.get("modality")) or ""
        pricing = object_or_empty(item.get("pricing"))

        return self.record(
            required_string(item.get("id"), "Cerebras model id"),
            context_length=integer(limits.get("max_context_length")),
            max_output_tokens=integer(limits.get("max_completion_tokens")),
            # modality is a plus-joined string, "text+vision", not a list
            input_modalities=[part.replace("vision", "image") for part in modality.split("+")] if modality else None,
            output_modalities=["text"] if modality else None,
            supports_tools=boolean(capabilities.get("function_calling")) or boolean(capabilities.get("tools")),
            supports_structured_output=boolean(capabilities.get("structured_outputs")),
            pricing=self.price(pricing.get("prompt"), pricing.get("completion")) if pricing else None,
            display_name=item.get("name"),
            hugging_face_id=item.get("hugging_face_id"),
            quantization=item.get("quantization"),
            # callable today either way, so these are flags on the record, not filters
            deprecated=item.get("deprecated") or None,
            preview=item.get("preview") or None,
            supported_parameters=sorted(k for k, v in object_or_empty(item.get("supported_parameters")).items() if v),
        )
