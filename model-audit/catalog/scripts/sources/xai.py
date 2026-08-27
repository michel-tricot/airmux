"""xAI.

**Two catalogs, and neither one is complete.** /v1/language-models is the membership list:
it returns only the text models, with modalities and pricing. /v1/models returns everything
xAI serves, image and video generation included, and it is the only endpoint carrying
context_length. So this reads both and merges: language-models decides what is in the
catalog, models supplies the window.

Filtering /v1/models alone would need a rule for telling grok from grok-imagine, and the
payload has no field that says which. Using the language-models list as the filter is the
vendor's own answer to that question.

**Prices are integers in USD cents per 100 million tokens.** Divide by 10,000 for dollars
per million. The spec says so on every price field and the published example agrees: 12500
is $1.25/Mtok. Read as dollars it is off by four orders of magnitude, and the value is
plausible enough at that scale to pass review unnoticed.

**Large prompts bill at a second rate.** Above long_context_threshold tokens the
*_long_context prices apply, and 0 in those fields means the standard rate carries on rather
than the model being free. The catalog has one price pair per model, so pricing holds the
standard tier and the threshold rides alongside it as long_context_threshold. A router that
ignores that field will under-bill long requests on the models that have one.

Every model carries `aliases`: grok-4 is an alias that follows a dated id like grok-4-0709.
Both forms are accepted on the wire and the alias is what the docs tell people to send, so
they are kept on the record. The catalog id stays the concrete one, because an alias that
silently repoints is not a routing key.

xAI also serves /v1/messages in Anthropic's shape and /v1/responses in OpenAI's. Only the
chat-completions surface is declared as ingress, matching how openai is recorded here: it
serves /v1/responses too and the catalog does not claim it.
"""

from model_audit.catalog_ops import ProviderDefinition, SchemaDefinition

from .base import ModelSource

# the spec quotes every token price in USD cents per 100 million tokens
CENTS_PER_HUNDRED_MILLION = 10_000


class XAI(ModelSource):
    id = "xai"
    url = "https://api.x.ai/v1/language-models"
    definition = ProviderDefinition(
        id=id,
        name="xAI",
        homepage="https://x.ai",
        docs="https://docs.x.ai",
        base_url="https://api.x.ai/v1",
        models_url=url,
        openapi="https://docs.x.ai/openapi.json",
        ingress=("oai", "anthropic"),
        auth=("bearer",),
        env_var="XAI_API_KEY",
        icon_mono="xai",
        icon_color="xai",
    )
    schemas = (
        SchemaDefinition(surface="oai", url=definition.openapi, path_pattern=r"^/v1/chat/completions$"),
        SchemaDefinition(surface="anthropic", url=definition.openapi, path_pattern=r"^/v1/messages$"),
    )

    def fetch(self, key):
        payload = self.get(self.url, key)
        # only /v1/models knows the context window, and only for the ids it shares with us
        windows = {model["id"]: model.get("context_length") for model in self.items(self.get("https://api.x.ai/v1/models", key)) if model.get("id")}
        for model in payload.get("models") or []:
            model["context_length"] = windows.get(model.get("id"))
        return payload

    def normalize(self, item):
        scale = lambda v: round(v / CENTS_PER_HUNDRED_MILLION, 4) if isinstance(v, (int, float)) else None
        prompt = scale(item.get("prompt_text_token_price"))
        cached = scale(item.get("cached_prompt_text_token_price"))

        return self.record(
            item["id"],
            context_length=item.get("context_length"),
            input_modalities=item.get("input_modalities"),
            output_modalities=item.get("output_modalities"),
            pricing={
                "input_per_mtok": prompt,
                "output_per_mtok": scale(item.get("completion_text_token_price")),
                **({"cached_input_per_mtok": cached} if cached else {}),
            }
            if prompt is not None
            else None,
            # zero means "no second tier", not "free above the threshold"
            long_context_threshold=item.get("long_context_threshold") or None,
            aliases=sorted(item.get("aliases") or []),
            owned_by=item.get("owned_by"),
            version=item.get("version"),
        )
