"""Fill context_length and max_output_tokens on every catalogued model.

Both fields are load-bearing for routing, so a null is a hole rather than a fact. This
walks the catalogs and fills gaps from, in order of preference:

  1. the provider's own catalog, where its listing endpoint already returned a limit
  2. OpenRouter's public model index, which publishes context_length for every model it
     serves and max_completion_tokens for most, and which carries hugging_face_id and
     canonical_slug so the same open-weights model can be matched across vendors
  3. LIMITS below, transcribed by hand from the vendor's own model page for the
     first-party models no aggregator covers

Every filled value records where it came from in limits_source, so a later correction can
tell a measured limit from a borrowed one.

    uv run python taxonomy/enrich_limits.py
"""

from __future__ import annotations

import json
import sys
import re
import ssl
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from canonical import write_catalog, write_schema
from paths import TAXONOMY

from model_kind import classify, text_only

ROOT = TAXONOMY
MODELS = ROOT / "models"
OR_INDEX = "https://openrouter.ai/api/v1/models"
CTX = ssl.create_default_context()

# Vendor-published limits for models no aggregator indexes. context, max output.
# Source is the vendor's own model reference page in every case.
LIMITS: dict[str, tuple[int, int]] = {}

def norm(model_id: str) -> str:
    """Reduce an id to something comparable across vendors."""
    s = model_id.lower().strip()
    s = s.split(":")[0]                       # openrouter variant suffixes
    s = re.sub(r"^accounts/[^/]+/models/", "", s)
    s = s.rsplit("/", 1)[-1]                  # drop the org prefix
    s = re.sub(r"[._]", "-", s)
    s = re.sub(r"-(fp8|bf16|nvfp4|hf|turbo|fast|instruct|it|latest)$", "", s)
    s = re.sub(r"-\d{6,8}$", "", s)           # trailing date stamps
    return s.strip("-")


def load_reference() -> dict[str, tuple[int | None, int | None]]:
    raw = urllib.request.urlopen(urllib.request.Request(OR_INDEX, headers={"User-Agent": "airllm-taxonomy/1.0"}), timeout=90, context=CTX).read()
    index: dict[str, tuple[int | None, int | None]] = {}
    for m in json.loads(raw)["data"]:
        ctx = m.get("context_length")
        top = m.get("top_provider") or {}
        mx = top.get("max_completion_tokens") or (ctx if top.get("context_length") == ctx else None)
        for key in filter(None, (m.get("id"), m.get("canonical_slug"), m.get("hugging_face_id"))):
            for candidate in (key.lower(), norm(key)):
                # first writer wins; ids are more specific than normalized forms
                index.setdefault(candidate, (ctx, mx))
    return index


def main() -> int:
    reference = load_reference()
    filled = {"self": 0, "openrouter": 0, "vendor": 0}
    still_null = []

    for f in sorted(MODELS.glob("*.json")):
        doc = json.loads(f.read_text())
        doc["models"] = text_only(doc["models"])
        doc["count"] = len(doc["models"])
        for model in doc["models"]:
            mid = model.get("id") or ""
            model["kind"] = classify(mid, model)

            if model.get("context_length") and model.get("max_output_tokens"):
                model.setdefault("limits_source", "provider")
                filled["self"] += 1
                continue

            source = model.get("limits_source")
            if mid in LIMITS:
                ctx, mx = LIMITS[mid]
                source = "vendor-docs"
            else:
                ctx = mx = None
                for key in (mid.lower(), norm(mid)):
                    if key in reference:
                        ctx, mx = reference[key]
                        source = "openrouter-index"
                        break

            if ctx and not model.get("context_length"):
                model["context_length"] = ctx
            if mx and not model.get("max_output_tokens"):
                model["max_output_tokens"] = mx
            if model.get("context_length") and model.get("max_output_tokens"):
                model["limits_source"] = source
                filled["openrouter" if source == "openrouter-index" else "vendor"] += 1
            else:
                still_null.append((doc["provider"], mid))

        write_catalog(f, doc)

    total = sum(filled.values()) + len(still_null)
    print(f"models: {total}")
    print(f"  complete from the provider itself  : {filled['self']}")
    print(f"  filled from the OpenRouter index   : {filled['openrouter']}")
    print(f"  filled from vendor docs            : {filled['vendor']}")
    print(f"  text models still incomplete       : {len(still_null)}")
    by_provider: dict[str, int] = {}
    for provider, _ in still_null:
        by_provider[provider] = by_provider.get(provider, 0) + 1
    for provider, n in sorted(by_provider.items(), key=lambda kv: -kv[1]):
        print(f"      {provider:<14} {n}")
    (ROOT / "reports").mkdir(exist_ok=True)
    (ROOT / "reports" / "missing-limits.json").write_text(json.dumps(sorted(still_null), indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
