"""Anthropic.

/v1/models needs the x-api-key header and an anthropic-version header; a bearer token is
parsed but is for OAuth tokens, not API keys.

The listing carries max_input_tokens and max_tokens, so limits never need borrowing here.
It also carries a nested capabilities tree, which is the only place Anthropic publishes
tool and structured-output support in machine-readable form. Read it rather than assuming:
capability differs across the family.

Pricing is not on the API and is not hardcoded here. A transcribed table lived in this
file and was wrong twice over: it froze on the day it was written, and because it was set
inside the source module every price was stamped pricing_source "provider", claiming
Anthropic published numbers it does not publish. enrich.py fills them from models.dev,
which covers the family and is fetched on every run.
"""

from .base import ModelSource


class Anthropic(ModelSource):
    id = "anthropic"

    def normalize(self, item):
        caps = item.get("capabilities") or {}

        def supported(name):
            return bool((caps.get(name) or {}).get("supported"))

        inputs = ["text"]
        if supported("image_input"):
            inputs.append("image")
        if supported("pdf_input"):
            inputs.append("pdf")
        return self.record(
            item["id"],
            context_length=item.get("max_input_tokens"),
            max_output_tokens=item.get("max_tokens"),
            input_modalities=inputs,
            output_modalities=["text"],
            supports_tools=supported("code_execution") or bool(caps),
            supports_structured_output=supported("structured_outputs"),
            display_name=item.get("display_name"),
            supports_thinking=supported("thinking"),
            supports_batch=supported("batch"),
        )
