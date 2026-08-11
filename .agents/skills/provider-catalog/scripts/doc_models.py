"""Model catalogs transcribed from provider documentation, for providers whose listing
endpoint needs a credential this machine does not have.

Every id below was read off the vendor's own models or pricing page, or off a model enum
in the vendor's OpenAPI spec, which is the better source where one exists because the
pricing pages print display names rather than API ids. Nothing here is inferred.

Files land in taxonomy/models/ alongside the API-fetched ones and carry source_type
"docs", so a later run of fetch_models.py with a real key overwrites them with source_type
"api". Prefer the API file when both exist: these lists go stale the moment a model ships.

    uv run python taxonomy/doc_models.py
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from canonical import write_catalog, write_schema
from paths import TAXONOMY

from model_kind import text_only

ROOT = TAXONOMY
OUT = ROOT / "models"
SPEC = ROOT / "schemas" / "completion"


def m(model_id, ctx=None, out=None):
    return {
        "id": model_id,
        "context_length": ctx,
        "max_output_tokens": out,
        "input_modalities": None,
        "output_modalities": None,
        "supports_tools": None,
        "supports_structured_output": None,
    }


def from_spec_enum(provider: str, filename: str) -> list[dict]:
    """Pull the model enum out of a schema we already extracted from the vendor's spec."""
    doc = json.loads((SPEC / filename).read_text())
    found: list[list[str]] = []

    def walk(node):
        if isinstance(node, dict):
            for k, v in node.items():
                if k == "model" and isinstance(v, dict):
                    enum = v.get("enum") or next((a.get("enum") for a in v.get("anyOf", []) if isinstance(a, dict) and a.get("enum")), None)
                    if enum:
                        found.append(enum)
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(doc)
    return [m(i) for i in sorted({i for e in found for i in e if isinstance(i, str)})]


# id -> (source url, models). Lists marked partial in NOTES are known-incomplete.
CATALOGS: dict[str, tuple[str, list[dict]]] = {
    "groq": ("https://console.groq.com/docs/models", [
        m("llama-3.1-8b-instant", 131072, 131072), m("llama-3.3-70b-versatile", 131072, 32768),
        m("openai/gpt-oss-120b", 131072, 65536), m("openai/gpt-oss-20b", 131072, 65536),
        m("whisper-large-v3"), m("whisper-large-v3-turbo"),
        m("groq/compound", 131072, 8192), m("groq/compound-mini", 131072, 8192),
        m("canopylabs/orpheus-arabic-saudi", 4000, 50000), m("canopylabs/orpheus-v1-english", 4000, 50000),
        m("meta-llama/llama-prompt-guard-2-22m", 512, 512), m("meta-llama/llama-prompt-guard-2-86m", 512, 512),
        m("minimaxai/minimax-m2.7", 196608, 131072), m("openai/gpt-oss-safeguard-20b", 131072, 65536),
        m("qwen/qwen3.6-27b", 131072, 16384),
    ]),
    "cerebras": ("https://inference-docs.cerebras.ai/models/overview", [
        m("gpt-oss-120b", 131072), m("gemma-4-31b", 131072), m("zai-glm-4.7", 131072),
    ]),
    "xai": ("https://docs.x.ai/docs/models", [
        m("grok-4.5", 500000), m("grok-4.3", 1000000),
        m("grok-4.20-0309-reasoning", 1000000),
        m("grok-4.20-0309-non-reasoning", 1000000),
        m("grok-4.20-multi-agent-0309", 1000000),
        m("grok-build-0.1", 256000),
        m("grok-imagine-image"), m("grok-imagine-image-quality"), m("grok-imagine-video"),
        m("grok-imagine-video-1.5"), m("grok-voice-think-fast-1.0"), m("grok-voice-think-fast-2.0"),
    ]),
    "mistral": ("https://docs.mistral.ai/getting-started/models/models_overview/", [
        m(i) for i in [
            "shieldstral-1-0", "mistral-medium-2604", "voxtral-tts-2603", "mistral-small-2603",
            "labs-leanstral-1-5", "mistral-large-2512", "mistral-ocr-4-0", "mistral-ocr-3-2512",
            "voxtral-mini-2602", "voxtral-mini-realtime-2602", "codestral-2508", "codestral-embed-2505",
            "ministral-3-14b-2512", "ministral-3-8b-2512", "ministral-3-3b-2512", "voxtral-small-2507",
            "mistral-moderation-2603", "mistral-embed-2312",
        ]
    ]),
    "cohere": ("https://docs.cohere.com/docs/models", [
        m("command-a-plus-05-2026", 128000, 64000), m("command-a-03-2025", 256000, 8000),
        m("command-a-reasoning-08-2025", 256000, 32000), m("command-a-vision-07-2025", 128000, 8000),
        m("command-a-translate-08-2025", 8000, 8000), m("command-r7b-12-2024", 128000, 4000),
        m("command-r-08-2024", 128000, 4000), m("command-r-plus-08-2024", 128000, 4000),
        m("command-r-03-2024", 128000, 4000), m("command-r-plus-04-2024", 128000, 4000),
        m("command-r-plus", 128000, 4000), m("command-r", 128000, 4000),
        m("command-light", 4000, 4000), m("command", 4000, 4000),
        m("embed-v4.0", 128000), m("embed-english-v3.0", 512), m("embed-english-light-v3.0", 512),
        m("embed-multilingual-v3.0", 512), m("embed-multilingual-light-v3.0", 512),
        m("rerank-v4.0-pro", 32000), m("rerank-v4.0-fast", 32000), m("rerank-v3.5", 4000),
        m("rerank-english-v3.0", 4000), m("rerank-multilingual-v3.0", 4000),
        m("cohere-transcribe-03-2026"),
        m("tiny-aya-global", 8000, 8000), m("tiny-aya-earth", 8000, 8000),
        m("tiny-aya-fire", 8000, 8000), m("tiny-aya-water", 8000, 8000),
        m("c4ai-aya-expanse-32b", 128000, 4000), m("c4ai-aya-expanse-8b", 8000, 4000),
        m("c4ai-aya-vision-32b", 16000, 4000), m("c4ai-aya-vision-8b", 16000, 4000),
    ]),
    "gemini": ("https://ai.google.dev/gemini-api/docs/models", [
        m(i) for i in [
            "gemini-3.6-flash", "gemini-3.5-flash", "gemini-3.5-flash-lite", "gemini-3.1-flash-lite",
            "gemini-3.1-flash-image", "gemini-3.1-flash-lite-image", "gemini-3-pro-image",
            "gemini-3.1-pro-preview", "gemini-3-flash-preview", "gemini-3.5-live-translate-preview",
            "gemini-3.1-flash-live-preview", "gemini-3.1-flash-tts-preview", "gemini-omni-flash",
            "gemini-2.5-flash", "gemini-2.5-flash-image", "gemini-2.5-flash-native-audio-preview-12-2025",
            "gemini-2.5-flash-preview-tts", "gemini-2.5-flash-lite", "gemini-2.5-pro",
            "gemini-2.5-pro-preview-tts", "gemini-2.5-computer-use-preview-10-2025",
            "gemini-embedding-2-preview", "gemini-embedding-001", "gemini-robotics-er-2-preview",
            "gemini-robotics-er-1.6-preview", "deep-research-preview-04-2026",
            "deep-research-max-preview-04-2026", "antigravity-preview-05-2026",
            "veo-3.1-generate-preview", "veo-3.1-lite-generate-preview",
            "lyria-3-pro-preview", "lyria-3-clip-preview", "lyria-realtime-exp",
        ]
    ]),
    "together": ("https://docs.together.ai/docs/serverless-models", [
        m("thinkingmachines/Inkling", 524288), m("thinkingmachines/Inkling-Small", 524288),
        m("MiniMaxAI/MiniMax-M3", 524288), m("Qwen/Qwen3.7-Max"), m("Qwen/Qwen3.6-Plus", 1000000),
        m("Qwen/Qwen3.7-Plus", 1000000), m("Qwen/Qwen3.5-9B", 262144),
        m("Qwen/Qwen2.5-7B-Instruct-Turbo", 32768), m("moonshotai/Kimi-K3", 1000000),
        m("moonshotai/Kimi-K2.7-Code", 262144), m("moonshotai/Kimi-K2.6", 262144),
        m("zai-org/GLM-5.2", 512000), m("openai/gpt-oss-120b", 128000), m("openai/gpt-oss-20b", 128000),
        m("deepseek-ai/DeepSeek-V4-Pro", 512000), m("deepseek-ai/DeepSeek-V4-Flash-0731", 1000000),
        m("nvidia/nemotron-3-ultra-550b-a55b", 512300), m("meta-llama/Llama-3.3-70B-Instruct-Turbo", 131072),
        m("google/gemma-4-31B-it", 262144), m("pearl-ai/gemma-4-31b-it", 32000),
        m("google/gemma-3n-E4B-it", 32768), m("deepcogito/cogito-v2-1-671b", 163840),
        m("LiquidAI/LFM2.5-8B-A1B", 32768), m("Prism-ML/Ternary-Bonsai-27B", 262144),
    ]),
    "perplexity": ("https://docs.perplexity.ai/api-reference/chat-completions-post", [
        m("sonar"), m("sonar-pro"), m("sonar-reasoning-pro"), m("sonar-deep-research"),
    ]),
    "baseten": ("https://docs.baseten.co/development/model-apis/overview", [
        m(i) for i in [
            "deepseek-ai/DeepSeek-V4-Pro", "deepseek-ai/DeepSeek-V4-Flash-0731",
            "zai-org/GLM-4.7", "zai-org/GLM-5.2", "zai-org/GLM-5.2-Fast",
            "thinkingmachines/Inkling", "thinkingmachines/Inkling-Small",
            "moonshotai/Kimi-K2.6", "moonshotai/Kimi-K2.7-Code", "moonshotai/Kimi-K3",
            "nvidia/Nemotron-Ultra", "openai/gpt-oss-120b",
        ]
    ]),
    "vertex": ("https://docs.cloud.google.com/gemini-enterprise-agent-platform/models", [
        m(i) for i in [
            "gemini-3.1-pro", "gemini-3-pro-image", "gemini-2.5-pro", "gemini-omni-flash-preview",
            "gemini-3.6-flash", "gemini-3.5-flash", "gemini-3.1-flash-image", "gemini-3-flash",
            "gemini-2.5-flash", "gemini-2.5-flash-image", "gemini-2.5-flash-live-api",
            "gemini-3.5-flash-lite", "gemini-3.1-flash-lite-image", "gemini-3.1-flash-lite",
            "gemini-2.5-flash-lite", "gemini-embedding-2", "gemini-robotics-er-2",
            "veo-2", "veo-3", "veo-3.1", "lyria-002", "lyria-3", "virtual-try-on-001",
            "claude-opus-5", "claude-sonnet-5", "claude-fable-5", "claude-opus-4.8", "claude-opus-4.7",
            "claude-sonnet-4.6", "claude-opus-4.6", "claude-opus-4.5", "claude-sonnet-4.5",
            "claude-opus-4.1", "claude-haiku-4.5", "claude-opus-4", "claude-sonnet-4",
            "mistral-medium-3", "mistral-ocr-25.05", "mistral-small-3.1-25.03", "codestral-2",
            "grok-4.1-fast", "grok-4.20", "grok-4.3",
            "llama-4-maverick", "llama-4-scout", "llama-3.3",
            "deepseek-v3.2", "deepseek-v3.1", "deepseek-r1-0528", "deepseek-ocr",
            "e5-multilingual-small", "e5-multilingual-large", "gemma-4-26b-a4b-it",
            "kimi-k2-thinking", "minimax-m2", "gpt-oss-120b", "gpt-oss-20b",
            "qwen-3-next-instruct-80b", "qwen-3-next-thinking-80b", "qwen-3-coder", "qwen-3-235b",
            "glm-5", "glm-4.7",
        ]
    ]),
}

# Providers whose OpenAPI spec carries the model enum: better than any pricing page,
# because the enum is the set the API itself validates against.
FROM_SPEC = {
    "deepseek": "oai.deepseek.request.json",
    "minimax": "oai.minimax.request.json",
    "moonshot": "oai.moonshot.request.json",
    "reka": "oai.reka.request.json",
    "upstage": "oai.upstage.request.json",
    "zai": "oai.zai.request.json",
}
SPEC_SOURCE = {
    "deepseek": "https://api-docs.deepseek.com/api/create-chat-completion",
    "minimax": "https://platform.minimax.io/docs/api-reference/text-openai-api",
    "moonshot": "https://platform.kimi.ai/docs/openapi.json",
    "reka": "https://docs.reka.ai/research/api-reference/create-chat-completion",
    "upstage": "https://console.upstage.ai/api/chat",
    "zai": "https://docs.z.ai/openapi.json",
}

NOTES = {
    "cerebras": "the overview page lists only the headline models; the full set needs a key",
    "mistral": "current models only; the page also lists deprecated ids with retirement dates",
    "vertex": "model garden ids; availability is per region and per project",
    "gemini": "the docs page does not publish token limits, so context is null throughout",
    "groq": "the vendor OpenAPI spec carries an older, shorter enum; the docs page is newer and used here",
}


def main() -> int:
    OUT.mkdir(exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    written = []

    for provider, filename in FROM_SPEC.items():
        CATALOGS[provider] = (SPEC_SOURCE[provider], from_spec_enum(provider, filename))

    for provider, (source, models) in sorted(CATALOGS.items()):
        models = text_only(models)
        existing = OUT / f"{provider}.json"
        if existing.exists() and json.loads(existing.read_text()).get("source_type") == "api":
            print(f"  keep    {provider:<13} already has an API-fetched catalog")
            continue
        doc = {
            "provider": provider,
            "source": source,
            "source_type": "docs",
            "updated": stamp,
            "count": len(models),
            "models": models,
        }
        if provider in NOTES:
            doc["note"] = NOTES[provider]
        write_catalog(existing, doc)
        written.append((provider, len(models)))

    for provider, n in written:
        print(f"  docs    {provider:<13} {n:>3} models")
    print(f"\n{len(written)} catalogs written from documentation")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
