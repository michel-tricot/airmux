"""DeepSeek.

/models is as bare as OpenAI's and shorter: id, object, owned_by, and two entries. No
context window, no output limit, no pricing, no capabilities. Limits and pricing come from
enrich.py; models.dev carries both.

Do not hardcode a price table here. The same table lived in openai.py and was wrong twice
over: frozen on the day it was written, and stamped pricing_source "provider" for numbers
the provider does not publish in any machine-readable form.

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

from .base import ModelSource


class DeepSeek(ModelSource):
    id = "deepseek"
    url = "https://api.deepseek.com/models"

    def normalize(self, item):
        return self.record(item["id"], owned_by=item.get("owned_by"))
