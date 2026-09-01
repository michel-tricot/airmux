"""Together AI.

Verified against a live account. /v1/models returns 280 models, 170 of them type "chat",
and the interesting question is which of those can actually be called without provisioning.

**Two fields look like the availability signal and neither is.**

`running` is false for all 170 chat models. It reports whether *your account* has a
dedicated endpoint up, not whether the model is servable, so filtering on it yields nothing.

`hourly` is 0 for every chat model, so it does not separate dedicated from serverless here
either, despite being the field that sounds like it would.

**Token pricing is the signal.** 74 of the 170 carry pricing.input > 0; the other 96 carry
zeroes throughout. On Together you pay per token for serverless and hourly for dedicated,
so a model with a per-token rate is one the account can call today. That 74 is three times
the 24 their serverless docs page lists, which is why this runs off the API.

**Pricing is already per million tokens.** Kimi K3 comes back as input 3, output 15, and
that is $3 and $15 per Mtok. Do not run it through the per-token conversion the other
sources need, or every Together price lands six orders of magnitude out.

Only type "chat" is taken. The payload also holds "language" base models, plus image,
video, audio, rerank and embedding, and model_kind would drop most of them anyway. Base
completion models are text but not chat-shaped, so they are excluded deliberately rather
than by accident.

The API publishes no tool or structured-output flags. The source fills those fields from
the current official serverless model table when it lists the same API id. The API remains
authoritative for context and pricing, and disagreements with the shorter documentation
catalog are retained as source conflicts.

Every callable chat model starts at text input and text output. Models repeated in the
official Vision table add image input without losing their text input.
"""

from model_audit.catalog_ops import ProviderDefinition, SchemaDefinition
from model_audit.provider_docs import apply_documentation, fetch_text, parse_together_models

from .base import ModelSource


class Together(ModelSource):
    id = "together"
    url = "https://api.together.ai/v1/models"
    serverless_only = True
    docs_catalog = "https://docs.together.ai/docs/serverless-models"
    definition = ProviderDefinition(
        id=id,
        name="Together AI",
        homepage="https://www.together.ai",
        docs="https://docs.together.ai",
        base_url="https://api.together.ai/v1",
        models_url=url,
        openapi="https://docs.together.ai/openapi.yaml",
        ingress=("oai",),
        primary_surface="oai",
        auth=("bearer",),
        env_var="TOGETHER_API_KEY",
        icon_mono="together",
        icon_color="together-color",
    )
    schemas = (SchemaDefinition(surface="oai", url=definition.openapi, path_pattern=r"chat/completions$"),)

    def items(self, payload):
        # the payload is a bare list, not the usual {"data": [...]}
        return payload if isinstance(payload, list) else super().items(payload)

    def normalize(self, item):
        if item.get("type") != "chat":
            return None
        pricing = item.get("pricing") or {}
        if not pricing.get("input"):
            return None  # no token rate means dedicated-only

        link = item.get("link") or ""
        return self.record(
            item["id"],
            context_length=item.get("context_length"),
            input_modalities=["text"],
            output_modalities=["text"],
            pricing={
                "input_per_mtok": pricing.get("input"),
                "output_per_mtok": pricing.get("output"),
                **({"cached_input_per_mtok": pricing["cached_input"]} if pricing.get("cached_input") else {}),
            },
            display_name=item.get("display_name"),
            organization=item.get("organization"),
            license=item.get("license"),
            hugging_face_id=link.removeprefix("https://huggingface.co/") if "huggingface.co" in link else None,
        )

    def enrich(self, models):
        documents = parse_together_models(fetch_text(self.docs_catalog), self.docs_catalog)
        by_id = {model_id: document for document in documents for model_id in document.ids}
        for model in models:
            document = by_id.get(str(model.get("id")))
            if document is None:
                continue
            for field in ("input_modalities", "output_modalities"):
                documented = document.values.get(field)
                if isinstance(documented, list):
                    model[field] = list(dict.fromkeys([*(model.get(field) or []), *documented]))
        return apply_documentation(models, documents)
