"""OpenAI.

/v1/models is deliberately bare: id, created, owned_by and shutdown_date. No context
window, no output limit, no pricing, no capabilities. Limits and pricing both come from
enrich.py, which fills them from live secondary sources.

Do not hardcode a price table here. One lived in this file and was wrong twice over: it
froze on the day it was written, so a new model got no price until someone edited the file,
and because it was set inside the source module every price was stamped
pricing_source "provider", claiming OpenAI published numbers it does not publish.
models.dev carries all of them and is fetched on every run.

Do not try to infer limits from the model id. The names encode marketing tiers, not
context windows, and the mapping has broken at every generation.

shutdown_date is worth carrying: it is the only machine-readable deprecation signal any
provider in the catalog publishes.
"""

from .base import ModelSource



class OpenAI(ModelSource):
    id = "openai"
    url = "https://api.openai.com/v1/models"

    def normalize(self, item):
        return self.record(item["id"], shutdown_date=item.get("shutdown_date"))
