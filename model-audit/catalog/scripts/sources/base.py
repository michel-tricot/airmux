"""One module per provider, because no two listing endpoints agree on anything.

A generic normalizer looks tempting and quietly throws data away. Groq returns pricing,
modalities and a feature list; Anthropic returns a capabilities tree; OpenAI returns four
fields and a shutdown date. Flattening those through one code path means the catalog holds
the intersection of what every vendor publishes, which is almost nothing.

So each provider gets a module under sources/ that subclasses ModelSource, declares how to
reach its catalog, and maps its own fields by hand. Add a provider by adding a module.
Nothing else changes: the registry is a subclass walk, not a list to edit.

Write the module's docstring for the next person. It is the right home for the per-provider
instructions that used to live in nobody's head: which endpoint is the real catalog, what
"serverless" means for that vendor, which fields lie, what the account has to look like.
"""

from __future__ import annotations

import json
import ssl
import urllib.error
import urllib.request
from typing import Any

CTX = ssl.create_default_context()
UA = {"User-Agent": "airllm-taxonomy/1.0", "Accept": "application/json"}


def per_mtok(value: Any) -> float | None:
    """Vendors quote per-token; the catalog stores per-million, rounded to the cent."""
    if value in (None, "", "0", 0):
        return 0.0 if value in ("0", 0) else None
    try:
        return round(float(value) * 1_000_000, 4)
    except (TypeError, ValueError):
        return None


class ModelSource:
    """Base for a provider's model catalog.

    Subclasses set `id` and `url`, then override `normalize`. Override `items` when the
    payload is not `{"data": [...]}`, and `fetch` when one request is not enough.
    """

    id: str = ""
    url: str = ""
    auth: str = "bearer"  # "bearer", "header:<Name>", or "none"
    open_access: bool = False  # catalog readable without a credential
    serverless_only: bool = False  # vendor lists models it will not serve on demand

    # ---- transport -------------------------------------------------------------

    def headers(self, key: str | None) -> dict[str, str]:
        head = dict(UA)
        if self.auth == "none" or not key:
            return head
        if self.auth.startswith("header:"):
            head[self.auth.split(":", 1)[1]] = key
        else:
            head["Authorization"] = f"Bearer {key}"
        return head

    def get(self, url: str, key: str | None) -> Any:
        request = urllib.request.Request(url, headers=self.headers(key))
        with urllib.request.urlopen(request, timeout=90, context=CTX) as response:
            return json.loads(response.read().decode())

    def fetch(self, key: str | None) -> Any:
        return self.get(self.url, key)

    # ---- shape -----------------------------------------------------------------

    def items(self, payload: Any) -> list[dict]:
        if isinstance(payload, list):
            return [i for i in payload if isinstance(i, dict)]
        if isinstance(payload, dict):
            for field in ("data", "models", "results", "items"):
                value = payload.get(field)
                if isinstance(value, list):
                    return [i for i in value if isinstance(i, dict)]
        return []

    def normalize(self, item: dict) -> dict | None:
        """Map one vendor record to a catalog record, or None to drop it.

        Return None for anything the account cannot call without provisioning: that is the
        whole point of the catalog, so a model in it is a model airllm can route to today.
        """
        raise NotImplementedError

    # ---- helpers for subclasses ------------------------------------------------

    @staticmethod
    def record(
        model_id: str,
        *,
        context_length: int | None = None,
        max_output_tokens: int | None = None,
        input_modalities: list[str] | None = None,
        output_modalities: list[str] | None = None,
        supports_tools: bool | None = None,
        supports_structured_output: bool | None = None,
        pricing: dict | None = None,
        **extra: Any,
    ) -> dict:
        out = {
            "id": model_id,
            "context_length": context_length,
            "max_output_tokens": max_output_tokens,
            "input_modalities": input_modalities,
            "output_modalities": output_modalities,
            "supports_tools": supports_tools,
            "supports_structured_output": supports_structured_output,
            "pricing": pricing,
        }
        out.update({k: v for k, v in extra.items() if v not in (None, [], {})})
        return out

    @staticmethod
    def price(input_per_token: Any, output_per_token: Any, **rest: Any) -> dict | None:
        priced = {
            "input_per_mtok": per_mtok(input_per_token),
            "output_per_mtok": per_mtok(output_per_token),
        }
        priced.update({k: per_mtok(v) for k, v in rest.items() if per_mtok(v) is not None})
        return priced if any(v is not None for v in priced.values()) else None


class GenericModelSource(ModelSource):
    def normalize(self, item: dict) -> dict | None:
        model_id = item.get("id")
        if not isinstance(model_id, str) or not model_id:
            return None
        return self.record(
            model_id,
            context_length=item.get("context_length") or item.get("context_window"),
            max_output_tokens=item.get("max_output_tokens") or item.get("max_completion_tokens"),
            input_modalities=item.get("input_modalities"),
            output_modalities=item.get("output_modalities"),
            owned_by=item.get("owned_by"),
        )


def registry() -> dict[str, ModelSource]:
    """Every ModelSource subclass in this package, keyed by provider id."""
    import importlib
    import pkgutil
    from pathlib import Path

    package = Path(__file__).parent
    for module in pkgutil.iter_modules([str(package)]):
        if module.name != "base":
            importlib.import_module(f"{__package__}.{module.name}")

    found: dict[str, ModelSource] = {}
    pending = list(ModelSource.__subclasses__())
    while pending:
        cls = pending.pop()
        pending.extend(cls.__subclasses__())
        if getattr(cls, "id", ""):
            found[cls.id] = cls()
    return found
