"""Bedrock Mantle's OpenAI-compatible Chat Completions endpoint.

The catalog route targets the in-region Mantle endpoint and accepts a Bedrock API key.
GPT-5.6 Terra is the documented representative model; its one-million-token price tier
is recorded so long prompts are not underpriced. Other listed ids are omitted until their
Chat Completions support and modality details are documented.
"""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING

from model_audit.catalog_ops import ProviderDefinition, SchemaDefinition

from .base import ModelSource, required_openapi

if TYPE_CHECKING:
    from model_audit.catalog_tasks.types import CatalogObject


class Bedrock(ModelSource):
    provider_id = "bedrock"
    url = "https://bedrock-mantle.us-east-1.api.aws/openai/v1/models"
    definition = ProviderDefinition(
        id=provider_id,
        name="Amazon Bedrock",
        homepage="https://aws.amazon.com/bedrock/",
        docs="https://docs.aws.amazon.com/bedrock/latest/userguide/inference-chat-completions.html",
        base_url="https://bedrock-mantle.us-east-1.api.aws/openai/v1",
        models_url=url,
        openapi="https://raw.githubusercontent.com/openai/openai-openapi/master/openapi.yaml",
        ingress=("oai",),
        primary_surface="oai",
        egress_kind="aws_bedrock",
        auth=("bearer",),
        env_var="AWS_BEARER_TOKEN_BEDROCK",
        icon_mono="bedrock",
    )
    schemas = (SchemaDefinition(surface="oai", url=required_openapi(definition), path_pattern=r"^/chat/completions$"),)

    def normalize(self, item: CatalogObject) -> CatalogObject | None:
        model_id = item.get("id")
        if not isinstance(model_id, str) or model_id != "openai.gpt-5.6-terra":
            return None
        return self.record(
            model_id,
            context_length=1_000_000,
            max_output_tokens=128_000,
            input_modalities=["text", "image"],
            output_modalities=["text"],
            supports_tools=True,
            pricing={
                "input_per_mtok": Decimal("4.40"),
                "cached_input_per_mtok": Decimal("0.44"),
                "cache_write_per_mtok": Decimal("5.50"),
                "output_per_mtok": Decimal("19.80"),
            },
        )
