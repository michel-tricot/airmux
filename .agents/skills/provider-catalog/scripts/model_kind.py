"""Classify a catalogued model by what it reads and writes.

The catalog tracks the completion surface, so it carries text models only. Everything else
a provider sells alongside them, embeddings and rerankers and image, video, speech and OCR
models, is dropped at the point of collection rather than filtered by every reader. A
context window and a max output token count are undefined for those, and a catalog whose
two load-bearing fields are null for a fifth of its rows is worse than a smaller one.

Classification is by id pattern first, then by declared output modality, because most
providers name these models unambiguously and only some declare modalities.
"""

from __future__ import annotations

import re

KINDS: list[tuple[str, str]] = [
    ("embedding", r"embed|bge-|e5-multilingual|gte-|voyage-(?!rerank)"),
    ("rerank", r"rerank"),
    ("speech-in", r"whisper|transcribe|\basr\b|stt|speech-to"),
    ("speech-out", r"\btts\b|text-to-speech|orpheus|voxtral-tts|realtime-tts|voice"),
    ("music", r"lyria"),
    ("video", r"video|veo-|seedance|wan2|t2v|vidu|pixverse|p-video|imagine-video"),
    ("image", r"image|dall-e|flux|seedream|imagen|cogview|bria|t2i|virtual-try-on|p-image|fibo"),
    ("ocr", r"\bocr\b|paddleocr|deplot"),
    ("moderation", r"moderation|guard|shieldstral|safeguard"),
    ("robotics", r"robotics"),
]


def classify(model_id: str, model: dict | None = None) -> str:
    lowered = (model_id or "").lower()
    for name, pattern in KINDS:
        if re.search(pattern, lowered):
            return name
    outputs = (model or {}).get("output_modalities") or []
    if outputs and "text" not in outputs:
        return "image" if "image" in outputs else "other"
    return "text"


def text_only(models: list[dict]) -> list[dict]:
    """Keep the text models, dropping everything else."""
    return [m for m in models if classify(m.get("id") or "", m) == "text"]
