"""Bedrock Mantle model IDs joined with AWS foundation model metadata and model cards."""

from __future__ import annotations

import json
import re
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING

from model_audit.catalog_ops import ProviderDefinition
from model_audit.catalog_tasks.types import integer, object_list, object_or_empty, string, strings

from .base import ModelSource

if TYPE_CHECKING:
    from model_audit.catalog_tasks.types import CatalogObject, CatalogValue

MODEL_CARDS = json.loads(Path(__file__).with_name("bedrock_models.json").read_text())
MODALITIES = {"TEXT": "text", "IMAGE": "image"}


def foundation_key(model_id: str) -> str:
    return re.sub(r"-(?:v)?\d+:\d+$", "", model_id)


class Bedrock(ModelSource):
    provider_id = "bedrock"
    url = "https://bedrock-mantle.us-east-1.api.aws/v1/models"
    metadata_url = "https://bedrock.us-east-1.amazonaws.com/foundation-models"
    definition = ProviderDefinition(
        id=provider_id,
        name="Amazon Bedrock",
        homepage="https://aws.amazon.com/bedrock/",
        docs="https://docs.aws.amazon.com/bedrock/latest/userguide/inference-chat-completions.html",
        base_url="https://bedrock-mantle.us-east-1.api.aws/v1",
        models_url=url,
        openapi=None,
        ingress=("oai",),
        primary_surface="oai",
        egress_kind="aws_bedrock",
        param_aliases=(("max_output_tokens", "max_completion_tokens"),),
        auth=("bearer",),
        env_var="AWS_BEARER_TOKEN_BEDROCK",
        icon_mono="bedrock",
    )

    def fetch(self, key: str | None) -> CatalogValue:
        listed = self.items(self.get(self.url, key))
        summaries = object_list(object_or_empty(self.get(self.metadata_url, key)).get("modelSummaries"))
        foundation = {foundation_key(model_id): item for item in summaries if (model_id := string(item.get("modelId")))}
        return {"data": [{**item, "foundation": foundation.get(string(item.get("id")))} for item in listed]}

    def normalize(self, item: CatalogObject) -> CatalogObject | None:
        model_id = string(item.get("id"))
        if model_id is None or model_id not in MODEL_CARDS or item.get("status") not in (None, "available"):
            return None
        card = object_or_empty(MODEL_CARDS[model_id])
        foundation = object_or_empty(item.get("foundation"))
        if foundation and object_or_empty(foundation.get("inferenceAPIsSupported")).get("openAiChatCompletions") is not True:
            return None
        inputs = [MODALITIES[value] for value in strings(foundation.get("inputModalities")) if value in MODALITIES]
        outputs = [MODALITIES[value] for value in strings(foundation.get("outputModalities")) if value in MODALITIES]
        max_output_tokens = integer(card.get("max_output_tokens"))
        return self.record(
            model_id,
            context_length=integer(card.get("context_length")),
            max_output_tokens=max_output_tokens,
            input_modalities=inputs or strings(card.get("input_modalities")),
            output_modalities=outputs or strings(card.get("output_modalities")),
            supports_tools=False if model_id == "openai.gpt-5.6-terra" else None,
            pricing={
                "input_per_mtok": Decimal("4.40"),
                "cached_input_per_mtok": Decimal("0.44"),
                "cache_write_per_mtok": Decimal("5.50"),
                "output_per_mtok": Decimal("19.80"),
            }
            if model_id == "openai.gpt-5.6-terra"
            else None,
            documentation_url=card.get("documentation_url"),
            base_url=f"https://bedrock-mantle.us-east-1.api.aws/{card['route']}",
            param_aliases={"max_tokens": "max_completion_tokens"} if card.get("route") == "openai/v1" else None,
            context_source="vendor-docs",
            max_output_source="vendor-docs" if max_output_tokens else None,
        )
