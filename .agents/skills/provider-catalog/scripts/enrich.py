"""Fill context window, output limit and pricing from secondary sources.

Most providers publish less than they charge for. Groq returns pricing and limits; Fireworks
returns limits and no pricing; OpenAI returns neither. Rather than leave the applied
taxonomy full of zeroes and defaults, gaps are filled from outside sources, in a fixed order
of trust, and every filled value records where it came from.

    uv run python enrich.py

## The order of trust

1. **The provider itself.** Whatever its own API returned is authoritative and never
   overwritten. This is the only source that is certainly right for that host.

2. **models.dev.** A community catalog, keyed by provider, so a Fireworks price is the
   price Fireworks charges rather than someone else's for the same weights. That makes it
   the better secondary source despite being community-maintained.

3. **The OpenRouter index.** Cross-provider: one entry per model, not per host. Correct for
   the model, possibly wrong for this host, because serving limits and prices differ
   between hosts for identical weights. Use it last and mark it.

Nothing here overwrites a provider's own value. A secondary source only fills a hole.

## Why the distinction is recorded rather than flattened

limits_source and pricing_source are separate because a record often has an authoritative
limit and a borrowed price. Flattening them into one confidence marker would lose exactly
the fact a reader needs before trusting a number in a routing decision.

A borrowed price is a good default and a bad guarantee. Do not bill from one.
"""

from __future__ import annotations

import json
import ssl
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from canonical import write_catalog
from model_kind import classify, text_only
from paths import TAXONOMY

CTX = ssl.create_default_context()
UA = {"User-Agent": "airllm-taxonomy/1.0", "Accept": "application/json"}
MODELS_DEV = "https://models.dev/api.json"
OPENROUTER = "https://openrouter.ai/api/v1/models"

# our provider id -> the id models.dev uses
MODELS_DEV_ID = {
    "openai": "openai",
    "anthropic": "anthropic",
    "groq": "groq",
    "fireworks": "fireworks-ai",
    "together": "togetherai",
}


def get(url: str):
    return json.loads(urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=120, context=CTX).read())


def norm(model_id: str) -> str:
    """Comparable form. Fireworks ids arrive fully qualified on models.dev."""
    s = (model_id or "").lower().strip()
    s = s.removeprefix("accounts/fireworks/models/")
    return s.rsplit("/", 1)[-1]


def per_mtok(value) -> float | None:
    try:
        return round(float(value) * 1_000_000, 4)
    except (TypeError, ValueError):
        return None


def load_models_dev() -> dict[tuple[str, str], dict]:
    """Provider-scoped, so the key is (our provider id, normalized model id)."""
    payload = get(MODELS_DEV)
    table: dict[tuple[str, str], dict] = {}
    for ours, theirs in MODELS_DEV_ID.items():
        for model_id, model in ((payload.get(theirs) or {}).get("models") or {}).items():
            cost, limit = model.get("cost") or {}, model.get("limit") or {}
            table[(ours, norm(model_id))] = {
                "context_length": limit.get("context"),
                "max_output_tokens": limit.get("output"),
                "pricing": {
                    "input_per_mtok": cost.get("input"),
                    "output_per_mtok": cost.get("output"),
                    **({"cached_input_per_mtok": cost["cache_read"]} if cost.get("cache_read") is not None else {}),
                    **({"cache_write_per_mtok": cost["cache_write"]} if cost.get("cache_write") is not None else {}),
                } if cost.get("input") is not None else None,
                "supports_tools": model.get("tool_call"),
                "supports_structured_output": model.get("structured_output"),
            }
    return table


def load_openrouter() -> dict[str, dict]:
    """Cross-provider, so the key is the normalized model id alone."""
    table: dict[str, dict] = {}
    for model in get(OPENROUTER)["data"]:
        cost = model.get("pricing") or {}
        top = model.get("top_provider") or {}
        record = {
            "context_length": model.get("context_length"),
            "max_output_tokens": top.get("max_completion_tokens"),
            "pricing": {
                "input_per_mtok": per_mtok(cost.get("prompt")),
                "output_per_mtok": per_mtok(cost.get("completion")),
            } if per_mtok(cost.get("prompt")) else None,
        }
        for key in filter(None, (model.get("id"), model.get("canonical_slug"), model.get("hugging_face_id"))):
            table.setdefault(norm(key), record)
    return table


def apply(model: dict, candidate: dict, source: str, counts: dict) -> None:
    """Fill only what is missing. A provider's own value is never overwritten."""
    if not model.get("context_length") and candidate.get("context_length"):
        model["context_length"] = candidate["context_length"]
        model.setdefault("limits_source", source)
    if not model.get("max_output_tokens") and candidate.get("max_output_tokens"):
        model["max_output_tokens"] = candidate["max_output_tokens"]
        model.setdefault("limits_source", source)
    if not model.get("pricing") and candidate.get("pricing"):
        model["pricing"] = candidate["pricing"]
        model["pricing_source"] = source
        counts[f"price:{source}"] = counts.get(f"price:{source}", 0) + 1
    for flag in ("supports_tools", "supports_structured_output"):
        if model.get(flag) is None and candidate.get(flag) is not None:
            model[flag] = candidate[flag]


def main() -> int:
    scoped, cross = load_models_dev(), load_openrouter()
    counts: dict[str, int] = {}
    totals = {"models": 0, "limits": 0, "priced": 0}
    gaps: list[tuple[str, str]] = []

    for path in sorted((TAXONOMY / "models").glob("*.json")):
        doc = json.loads(path.read_text())
        provider = doc["provider"]
        doc["models"] = text_only(doc["models"])
        for model in doc["models"]:
            model["kind"] = classify(model["id"], model)
            # mark what the provider itself supplied, before any gap is filled. limits and
            # pricing are marked independently: a record commonly has one and not the other
            if model.get("context_length") and model.get("max_output_tokens"):
                model.setdefault("limits_source", "provider")
            if model.get("pricing"):
                model.setdefault("pricing_source", "provider")
            key = norm(model["id"])
            if (provider, key) in scoped:
                apply(model, scoped[(provider, key)], "models.dev", counts)
            if key in cross:
                apply(model, cross[key], "openrouter-index", counts)

            totals["models"] += 1
            totals["limits"] += bool(model.get("context_length") and model.get("max_output_tokens"))
            totals["priced"] += bool(model.get("pricing"))
            if not (model.get("context_length") and model.get("pricing")):
                gaps.append((provider, model["id"]))
        write_catalog(path, doc)

    print(f"models: {totals['models']}")
    print(f"  with both limits : {totals['limits']}")
    print(f"  with pricing     : {totals['priced']}")
    for source, n in sorted(counts.items()):
        print(f"    {source:<28} {n}")
    print(f"  still missing a limit or a price: {len(gaps)}")
    (TAXONOMY / "reports").mkdir(exist_ok=True)
    (TAXONOMY / "reports" / "missing-limits.json").write_text(json.dumps(sorted(gaps), indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
