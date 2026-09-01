"""DeepSeek.

/models is bare: id, object, and owned_by. The official pricing page supplies limits,
modalities, capabilities, peak rates, and off-peak rates. Peak rates are the safe default;
both schedules remain represented as named pricing tiers.

Do not hardcode a price table here. The documentation extractor runs on every sync and
records its exact source URL as vendor documentation rather than provider API metadata.

Do not read the model list off the pricing page either. The docs name deepseek-v4-flash and
deepseek-v4-pro as the ids to send while secondary catalogs still carry deepseek-chat and
deepseek-reasoner, which are the older aliases. The listing endpoint is the one that says
what this account can call today, which is the question the catalog answers.

DeepSeek serves three surfaces on one key: /chat/completions in OpenAI's shape,
/anthropic/v1/messages in Anthropic's, and /responses. Only the first two are declared as
ingress, matching how openai is recorded here. The base URL takes /v1 or omits it; both
reach the same route, and the segment is compatibility padding for OpenAI SDKs rather than
a version.

There is no OpenAPI spec. api-docs.deepseek.com is a Docusaurus site that answers HTTP 200
with the SPA shell for every path, so openapi.json, api.json and static/openapi.json all
"succeed" and return HTML. The request schema is transcribed from the parameter table in
doc_schemas.py instead.
"""

from __future__ import annotations

from model_audit.catalog_ops import ProviderDefinition
from model_audit.provider_docs import apply_documentation, fetch_text, parse_deepseek_pricing

from .base import ModelSource


class DeepSeek(ModelSource):
    id = "deepseek"
    url = "https://api.deepseek.com/models"
    pricing_url = "https://api-docs.deepseek.com/quick_start/pricing/"
    definition = ProviderDefinition(
        id=id,
        name="DeepSeek",
        homepage="https://www.deepseek.com",
        docs="https://api-docs.deepseek.com",
        base_url="https://api.deepseek.com",
        models_url=url,
        ingress=("oai", "anthropic"),
        primary_surface="oai",
        auth=("bearer",),
        env_var="DEEPSEEK_API_KEY",
        icon_mono="deepseek",
        icon_color="deepseek-color",
    )

    def normalize(self, item):
        return self.record(item["id"], owned_by=item.get("owned_by"))

    def enrich(self, models):
        documents = tuple(parse_deepseek_pricing(fetch_text(self.pricing_url), self.pricing_url).values())
        return apply_documentation(models, documents)
