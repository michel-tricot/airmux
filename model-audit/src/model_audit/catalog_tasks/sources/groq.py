"""Groq.

The authenticated catalog is far richer than the unauthenticated one: with a key,
/openai/v1/models returns pricing, context window, modalities and a feature list. Without
one it returns 401. Always fetch with the key.

Everything Groq lists is serverless. There is no provisioning concept, so no filtering is
needed beyond the `active` flag, which marks models it will still route.

Pricing is per token as a decimal string, including a separate cached-input rate.
supported_features is the authoritative tool and JSON-mode signal; do not infer either
from the model name.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from model_audit.catalog_ops import ProviderDefinition, SchemaDefinition
from model_audit.catalog_tasks.types import integer, object_or_empty, required_string, strings

from .base import ModelSource

if TYPE_CHECKING:
    from model_audit.catalog_tasks.types import CatalogObject


class Groq(ModelSource):
    provider_id = "groq"
    url = "https://api.groq.com/openai/v1/models"
    definition = ProviderDefinition(
        id=provider_id,
        name="Groq",
        homepage="https://groq.com",
        docs="https://console.groq.com/docs",
        base_url="https://api.groq.com/openai/v1",
        models_url=url,
        openapi="https://raw.githubusercontent.com/groq/groq-python/main/.stats.yml",
        ingress=("oai",),
        primary_surface="oai",
        auth=("bearer",),
        env_var="GROQ_API_KEY",
        icon_mono="groq",
        icon_color="groq",
    )
    schemas = (
        SchemaDefinition(
            surface="oai",
            url="https://storage.googleapis.com/stainless-sdk-openapi-specs/groqcloud/groqcloud-debd965baa031e12228c41e538741fa6055bf2813bcd062840a19f84a17cea95.yml",
            path_pattern=r"chat/completions$",
        ),
    )

    def normalize(self, item: CatalogObject) -> CatalogObject | None:
        if item.get("active") is False:
            return None
        features = strings(item.get("supported_features"))
        pricing = object_or_empty(item.get("pricing"))
        return self.record(
            required_string(item.get("id"), "Groq model id"),
            context_length=integer(item.get("context_window")) or integer(item.get("context_length")),
            max_output_tokens=integer(item.get("max_completion_tokens")) or integer(item.get("max_output_length")),
            input_modalities=strings(item.get("input_modalities")) or None,
            output_modalities=strings(item.get("output_modalities")) or None,
            supports_tools="tools" in features,
            supports_structured_output="json_mode" in features or "structured_outputs" in features,
            pricing=self.price(
                pricing.get("prompt"),
                pricing.get("completion"),
                cached_input_per_mtok=pricing.get("input_cache_read"),
            ),
            display_name=item.get("name"),
            hugging_face_id=item.get("hugging_face_id"),
        )
