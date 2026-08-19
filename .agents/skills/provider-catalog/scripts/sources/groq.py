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

from .base import ModelSource


class Groq(ModelSource):
    id = "groq"

    def normalize(self, item):
        if item.get("active") is False:
            return None
        features = item.get("supported_features") or []
        pricing = item.get("pricing") or {}
        return self.record(
            item["id"],
            context_length=item.get("context_window") or item.get("context_length"),
            max_output_tokens=item.get("max_completion_tokens") or item.get("max_output_length"),
            input_modalities=item.get("input_modalities"),
            output_modalities=item.get("output_modalities"),
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
