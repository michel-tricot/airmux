"""Build request schemas for providers that publish no usable OpenAPI spec.

Every property here was read off the vendor's own parameter table; nothing is inferred
from OpenAI's schema. Providers whose docs enumerate no parameters at all are handled in
providers.yml by pointing at the canonical schema instead, not by inventing one here.
"""

import json
import sys
from pathlib import Path

from canonical import write_catalog, write_schema
from paths import TAXONOMY
from sources import registry

OUT = TAXONOMY / "schemas" / "completion"
OUT.mkdir(parents=True, exist_ok=True)

MESSAGES = {
    "type": "array",
    "minItems": 1,
    "items": {
        "type": "object",
        "required": ["role"],
        "properties": {
            "role": {"type": "string", "enum": ["system", "developer", "user", "assistant", "tool"]},
            "content": {"type": ["string", "array", "null"]},
            "name": {"type": "string"},
            "tool_calls": {"type": "array"},
            "tool_call_id": {"type": "string"},
        },
    },
}
TOOLS = {
    "type": "array",
    "items": {
        "type": "object",
        "required": ["type", "function"],
        "properties": {
            "type": {"type": "string", "enum": ["function"]},
            "function": {
                "type": "object",
                "required": ["name"],
                "properties": {
                    "name": {"type": "string"},
                    "description": {"type": "string"},
                    "parameters": {"type": "object"},
                    "strict": {"type": ["boolean", "null"]},
                },
            },
        },
    },
}
TOOL_CHOICE = {"oneOf": [{"type": "string", "enum": ["none", "auto", "required"]}, {"type": "object"}]}
STREAM_OPTIONS = {"type": ["object", "null"], "properties": {"include_usage": {"type": "boolean"}}}
STOP = {"type": ["string", "array", "null"], "items": {"type": "string"}}


def schema(title, source, required, props, extra=True, notes=None):
    out = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": title,
        "description": f"Request body for the completion endpoint. Transcribed from {source}",
        "type": "object",
        "required": required,
        "properties": props,
        "additionalProperties": extra,
    }
    if notes:
        out["x-notes"] = notes
    return out


BUILD = {}

BUILD["deepseek.oai"] = schema(
    "DeepSeek chat completion request",
    "https://api-docs.deepseek.com/api/create-chat-completion",
    ["model", "messages"],
    {
        "model": {"type": "string", "enum": ["deepseek-v4-flash", "deepseek-v4-pro"]},
        "messages": MESSAGES,
        "thinking": {
            "type": "object",
            "properties": {
                "type": {"type": "string", "enum": ["enabled", "disabled"], "default": "enabled"},
                "reasoning_effort": {"type": "string", "enum": ["low", "high", "max"], "default": "high"},
            },
        },
        "max_tokens": {"type": "integer"},
        "response_format": {"type": "object", "properties": {"type": {"type": "string", "enum": ["text", "json_object"], "default": "text"}}},
        "stop": {"type": ["string", "array", "null"], "items": {"type": "string"}, "maxItems": 16},
        "stream": {"type": "boolean"},
        "stream_options": STREAM_OPTIONS,
        "temperature": {"type": "number", "maximum": 2, "default": 1},
        "top_p": {"type": "number", "maximum": 1, "default": 1},
        "tools": dict(TOOLS, maxItems=128),
        "tool_choice": TOOL_CHOICE,
        "logprobs": {"type": "boolean"},
        "top_logprobs": {"type": "integer", "maximum": 20},
        "user_id": {"type": "string", "maxLength": 512},
    },
    notes=[
        "frequency_penalty and presence_penalty are documented as no longer supported and are ignored if sent",
        "reasoning_effort maps medium and xhigh onto high rather than rejecting them",
    ],
)

BUILD["fireworks.oai"] = schema(
    "Fireworks AI chat completion request",
    "https://docs.fireworks.ai/api-reference/post-chatcompletions",
    ["model"],
    {
        "model": {"type": "string"},
        "messages": MESSAGES,
        "tools": TOOLS,
        "tool_choice": {"oneOf": [{"type": "string", "enum": ["auto", "none", "any", "required"]}, {"type": "object"}], "default": "auto"},
        "function_call": {"oneOf": [{"type": "string", "enum": ["auto", "none"]}, {"type": "object"}, {"type": "null"}]},
        "functions": {"type": "array"},
        "stream": {"type": ["boolean", "null"], "default": False},
        "stream_options": STREAM_OPTIONS,
        "response_format": {"type": ["object", "null"]},
        "temperature": {"type": ["number", "null"], "minimum": 0, "maximum": 2},
        "top_p": {"type": ["number", "null"], "minimum": 0, "maximum": 1},
        "top_k": {"type": ["integer", "null"], "minimum": 0, "maximum": 100},
        "min_p": {"type": ["number", "null"], "minimum": 0, "maximum": 1},
        "typical_p": {"type": ["number", "null"], "minimum": 0, "maximum": 1},
        "n": {"type": "integer", "minimum": 1, "maximum": 128, "default": 1},
        "service_tier": {"type": "string", "enum": ["auto", "default", "flex", "priority"], "default": "default"},
        "stop": STOP,
        "max_tokens": {"type": ["integer", "null"]},
        "max_completion_tokens": {"type": ["integer", "null"]},
        "frequency_penalty": {"type": ["number", "null"], "minimum": -2, "maximum": 2},
        "presence_penalty": {"type": ["number", "null"], "minimum": -2, "maximum": 2},
        "repetition_penalty": {"type": ["number", "null"], "minimum": 0, "maximum": 2},
        "mirostat_target": {"type": ["number", "null"]},
        "mirostat_lr": {"type": ["number", "null"]},
        "seed": {"type": ["integer", "null"]},
        "logprobs": {"type": ["integer", "boolean", "null"], "minimum": 0, "maximum": 5},
        "top_logprobs": {"type": ["integer", "null"], "minimum": 0, "maximum": 5},
        "logit_bias": {"type": ["object", "null"]},
        "sampling_mask": {"type": ["string", "null"], "enum": ["count", "non_zero_list", "non_zero_buffer", None]},
        "echo": {"type": ["boolean", "null"], "default": False},
        "echo_last": {"type": ["integer", "null"]},
        "ignore_eos": {"type": "boolean", "default": False},
        "context_length_exceeded_behavior": {"type": "string", "enum": ["error", "truncate"], "default": "truncate"},
        "speculation": {"type": ["string", "array", "null"]},
        "prediction": {"type": ["object", "string", "null"]},
        "metadata": {"type": ["object", "null"]},
        "reasoning_effort": {"type": ["string", "integer", "boolean", "null"]},
        "reasoning_history": {"type": ["string", "null"], "enum": ["disabled", "interleaved", "preserved", None]},
        "thinking": {"type": ["object", "null"]},
        "return_token_ids": {"type": ["boolean", "null"], "default": False},
        "prompt_token_ids": {"type": ["array", "null"]},
        "prompt_truncate_len": {"type": ["integer", "null"]},
        "parallel_tool_calls": {"type": ["boolean", "null"]},
        "safe_tokenization": {"type": ["boolean", "null"]},
        "raw_output": {"type": ["boolean", "null"], "default": False},
        "perf_metrics_in_response": {"type": ["boolean", "null"], "default": False},
        "prompt_cache_key": {"type": ["string", "null"]},
        "prompt_cache_isolation_key": {"type": ["string", "null"]},
        "user": {"type": ["string", "null"]},
    },
)

for source in registry().values():
    for surface, document in source.documented_schemas.items():
        BUILD[f"{source.id}.{surface}"] = document

selected = set(sys.argv[1:])
written = 0
for name, doc in BUILD.items():
    provider, ingress = name.split(".")
    if selected and provider not in selected and name not in selected:
        continue
    write_schema(OUT / f"{ingress}.{provider}.request.json", doc)
    print(f"{ingress}.{provider}.request: props={len(doc['properties'])} required={doc['required']}")
    written += 1

print("\nwrote", written, "documentation-derived schemas")
