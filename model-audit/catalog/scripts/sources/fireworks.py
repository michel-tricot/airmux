"""Fireworks AI.

Verified against a live account. Two things here will mislead anyone who trusts the
obvious reading.

**The obvious endpoint is the wrong one.** /inference/v1/models lists the account's OWN
deployments and returns an empty list for a normal account, which reads as "Fireworks has
no models". The public catalog is the control plane, /v1/accounts/fireworks/models, and it
paginates: 297 models at the time of writing, 200 per page, so follow nextPageToken.

**Almost nothing in that catalog is serverless.** 297 models, 20 of them serverless and
READY. The rest need a deployment provisioned, which is exactly what the catalog exists to
exclude. Their public models page shows all 297 with no usable distinction, so transcribing
it produces a list where nine in ten entries cannot be called. Filter on supportsServerless
and state == READY and trust nothing else.

Serverless models come back as kind HF_BASE_MODEL, plus a couple of EMBEDDING_MODEL that
model_kind drops later. Do not filter on kind directly; it has more values than it looks
and the serverless flag is the real signal.

Fireworks publishes no pricing on the model API. The source reads the official serverless
pricing document on every sync, preserves standard rates as the default, and records
priority rates as a named tier. Community catalogs fill only models absent from that page.

Model ids on the wire are fully qualified, accounts/fireworks/models/<name>. The bare name
is accepted for some models and 404s for others, so upstream_id always carries the
qualified form while id stays short for the catalog.

deprecationDate arrives as {year, month, day} rather than a string, and is worth carrying:
with OpenAI's shutdown_date it is one of only two machine-readable deprecation signals in
the whole catalog.
"""

from model_audit.catalog_ops import ProviderDefinition
from model_audit.provider_docs import apply_documentation, fetch_text, fetch_texts, parse_fireworks_model, parse_fireworks_pricing

from .base import ModelSource


class Fireworks(ModelSource):
    id = "fireworks"
    url = "https://api.fireworks.ai/v1/accounts/fireworks/models?pageSize=200"
    serverless_only = True
    pricing_url = "https://docs.fireworks.ai/serverless/pricing.md"
    model_docs = "https://app.fireworks.ai/models/fireworks/"
    definition = ProviderDefinition(
        id=id,
        name="Fireworks AI",
        homepage="https://fireworks.ai",
        docs="https://docs.fireworks.ai",
        base_url="https://api.fireworks.ai/inference/v1",
        models_url=url,
        ingress=("oai",),
        auth=("bearer",),
        env_var="FIREWORKS_API_KEY",
        icon_mono="fireworks",
        icon_color="fireworks-color",
    )

    def fetch(self, key):
        collected, url = [], self.url
        for _ in range(10):  # 297 models at 200 a page, with headroom
            payload = self.get(url, key)
            collected.extend(payload.get("models") or [])
            token = payload.get("nextPageToken")
            if not token:
                break
            url = f"{self.url}&pageToken={token}"
        return {"models": collected}

    def normalize(self, item):
        # the whole point of the catalog: callable today, no deployment to provision
        if not item.get("supportsServerless") or item.get("state") != "READY":
            return None
        model_id = (item.get("name") or "").split("/")[-1]
        if not model_id:
            return None

        deprecation = item.get("deprecationDate") or {}
        sunset = (
            f"{deprecation['year']:04d}-{deprecation['month']:02d}-{deprecation['day']:02d}" if {"year", "month", "day"} <= set(deprecation) else None
        )
        hf_url = item.get("huggingFaceUrl") or ""

        return self.record(
            model_id,
            # The wire id is the fully qualified name. The bare name works for some models
            # and 404s for others, with nothing on the record to say which, so always send
            # the qualified form: gpt-oss-120b answers bare, gpt-oss-20b does not.
            upstream_id=item.get("name"),
            context_length=item.get("contextLength"),
            input_modalities=["text", "image"] if item.get("supportsImageInput") else ["text"],
            output_modalities=["text"],
            supports_tools=item.get("supportsTools"),
            pricing=None,  # not published on the API, see the docstring
            display_name=item.get("displayName"),
            hugging_face_id=hf_url.removeprefix("https://huggingface.co/") or None,
            deprecation_date=sunset,
        )

    def enrich(self, models):
        documents = tuple(parse_fireworks_pricing(fetch_text(self.pricing_url), self.pricing_url).values())
        enriched = apply_documentation(models, documents)
        urls = tuple(f"{self.model_docs}{model['id']}" for model in enriched if model.get("pricing") is None)
        model_documents = tuple(parse_fireworks_model(document, url) for url, document in fetch_texts(urls).items())
        return apply_documentation(enriched, model_documents)
