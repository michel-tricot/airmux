"""Build request schemas for providers that publish no usable OpenAPI spec.

Every property here was read off the vendor's own parameter table; nothing is inferred
from OpenAI's schema. Providers whose docs enumerate no parameters at all are handled in
providers.yml by pointing at the canonical schema instead, not by inventing one here.
"""

import json
from pathlib import Path

from canonical import write_catalog, write_schema
from paths import TAXONOMY

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

BUILD["gemini.oai"] = schema(
    "Google Gemini OpenAI-compatibility layer chat completion request",
    "https://ai.google.dev/gemini-api/docs/openai",
    ["model", "messages"],
    {
        "model": {"type": "string"},
        "messages": MESSAGES,
        "stream": {"type": "boolean"},
        "tools": TOOLS,
        "tool_choice": TOOL_CHOICE,
        "reasoning_effort": {"type": "string", "enum": ["none", "minimal", "low", "medium", "high"]},
        "service_tier": {"type": "string", "enum": ["standard", "flex", "priority"]},
        "extra_body": {
            "type": "object",
            "properties": {
                "cached_content": {"type": "string"},
                "thinking_config": {
                    "type": "object",
                    "properties": {"thinking_level": {"type": "string"}, "include_thoughts": {"type": "boolean"}},
                },
                "safety_settings": {"type": "array"},
            },
        },
    },
    notes=[
        "The compatibility layer silently ignores any parameter not documented here or under extra_body",
        "Google documents OpenAI library support as beta",
    ],
)

BUILD["minimax.oai"] = schema(
    "MiniMax OpenAI-compatible chat completion request",
    "https://platform.minimax.io/docs/api-reference/text-openai-api",
    ["model", "messages"],
    {
        "model": {
            "type": "string",
            "enum": ["MiniMax-M3", "MiniMax-M2.7", "MiniMax-M2.7-highspeed", "MiniMax-M2.5", "MiniMax-M2.5-highspeed", "MiniMax-M2.1", "MiniMax-M2.1-highspeed", "MiniMax-M2"],
        },
        "messages": MESSAGES,
        "thinking": {"type": "object", "properties": {"type": {"type": "string", "enum": ["disabled", "adaptive"]}}},
        "max_tokens": {"type": "integer", "minimum": 1},
        "max_completion_tokens": {"type": "integer", "minimum": 1},
        "temperature": {"type": "number", "minimum": 0, "maximum": 2, "default": 1},
        "top_p": {"type": "number", "minimum": 0, "maximum": 1},
        "tools": TOOLS,
        "reasoning_split": {"type": "boolean"},
        "service_tier": {"type": "string", "enum": ["standard", "priority"], "default": "standard"},
        "stream": {"type": "boolean"},
        "stream_options": STREAM_OPTIONS,
        "n": {"type": "integer", "enum": [1]},
    },
    notes=[
        "presence_penalty, frequency_penalty and logit_bias are accepted but ignored",
        "n accepts only the value 1",
        "top_p defaults to 0.95 on M3 and 0.9 on the M2 series",
    ],
)

BUILD["novita.oai"] = schema(
    "Novita AI chat completion request",
    "https://novita.ai/docs/guides/llm-api",
    ["model", "messages"],
    {
        "model": {"type": "string"},
        "messages": MESSAGES,
        "temperature": {"type": "number"},
        "top_p": {"type": "number"},
        "top_k": {"type": "number"},
        "presence_penalty": {"type": "number"},
        "frequency_penalty": {"type": "number"},
        "repetition_penalty": {"type": "number"},
        "max_tokens": {"type": "number"},
        "stream": {"type": "boolean", "default": False},
        "stop": STOP,
    },
    notes=["The vendor spec at novita.ai/openapi.json declares the path but carries no request body"],
)

BUILD["sambanova.oai"] = schema(
    "SambaNova Cloud chat completion request",
    "https://docs.sambanova.ai/docs/api-reference/chat-completions/create-chat-based-completion",
    ["model", "messages"],
    {
        "model": {"type": "string"},
        "messages": MESSAGES,
        "max_tokens": {"type": ["integer", "null"]},
        "max_completion_tokens": {"type": ["integer", "null"]},
        "temperature": {"type": ["number", "null"], "minimum": 0, "maximum": 2, "default": 0.7},
        "top_p": {"type": ["number", "null"], "minimum": 0, "maximum": 1},
        "top_k": {"type": ["integer", "null"], "minimum": 1, "maximum": 100},
        "presence_penalty": {"type": ["number", "null"], "minimum": -2, "maximum": 2, "default": 0},
        "frequency_penalty": {"type": ["number", "null"], "minimum": -2, "maximum": 2, "default": 0},
        "do_sample": {"type": ["boolean", "null"]},
        "stop": STOP,
        "stream": {"type": ["boolean", "null"], "default": False},
        "stream_options": STREAM_OPTIONS,
        "response_format": {"type": ["object", "null"]},
        "reasoning_effort": {"type": ["string", "null"], "enum": ["low", "medium", "high", None]},
        "tools": dict(TOOLS, maxItems=128),
        "tool_choice": TOOL_CHOICE,
        "parallel_tool_calls": {"type": ["boolean", "null"]},
        "chat_template_kwargs": {"type": ["object", "null"], "properties": {"enable_thinking": {"type": "boolean"}}},
        "logprobs": {"type": ["boolean", "null"], "default": False},
        "top_logprobs": {"type": ["integer", "null"], "minimum": 0, "maximum": 20},
        "n": {"type": ["integer", "null"], "minimum": 1, "maximum": 8, "default": 1},
        "logit_bias": {"type": ["object", "null"]},
        "seed": {"type": ["integer", "null"]},
    },
    notes=["presence_penalty and frequency_penalty are documented as not currently implemented"],
)

BUILD["upstage.oai"] = schema(
    "Upstage Solar chat completion request",
    "https://console.upstage.ai/api/chat",
    ["model", "messages"],
    {
        "model": {"type": "string", "enum": ["solar-pro4", "solar-pro3", "solar-pro2", "solar-mini", "syn-pro"]},
        "messages": MESSAGES,
        "max_tokens": {"type": "integer", "minimum": 1},
        "temperature": {"type": "number", "minimum": 0, "maximum": 2},
        "top_p": {"type": "number", "minimum": 0, "maximum": 1},
        "stream": {"type": "boolean", "default": False},
        "frequency_penalty": {"type": "number", "minimum": -2, "maximum": 2, "default": 1.1},
        "presence_penalty": {"type": "number", "minimum": -2, "maximum": 2, "default": 0.0},
        "reasoning_effort": {"type": "string", "enum": ["none", "minimal", "low", "medium", "high", "xhigh", "max"]},
        "tools": dict(TOOLS, maxItems=128),
        "tool_choice": TOOL_CHOICE,
        "parallel_tool_calls": {"type": "boolean", "default": True},
        "response_format": {"type": "object"},
        "prompt_cache_key": {"type": "string"},
    },
    notes=["temperature defaults to 0.8 on solar-pro3 and 0.7 elsewhere; top_p defaults to 0.95 on solar-pro3 and 1.0 elsewhere"],
)

BUILD["reka.oai"] = schema(
    "Reka AI chat completion request",
    "https://docs.reka.ai/research/api-reference/create-chat-completion",
    ["messages", "model"],
    {
        "messages": MESSAGES,
        "model": {"type": "string", "enum": ["reka-flash-research"], "default": "reka-flash-research"},
        "stream": {"type": "boolean", "default": False},
        "research": {
            "type": "object",
            "properties": {
                "web_search": {
                    "type": "object",
                    "properties": {
                        "enabled": {"type": "boolean", "default": True},
                        "max_uses": {"type": "integer"},
                        "allowed_domains": {"type": "array", "items": {"type": "string"}},
                        "blocked_domains": {"type": "array", "items": {"type": "string"}},
                        "user_location": {
                            "type": "object",
                            "properties": {
                                "type": {"type": "string", "default": "approximate"},
                                "approximate": {
                                    "type": "object",
                                    "properties": {
                                        "city": {"type": "string"},
                                        "region": {"type": "string"},
                                        "country": {"type": "string"},
                                        "timezone": {"type": "string"},
                                    },
                                },
                            },
                        },
                    },
                },
                "parallel_thinking": {"type": "object", "properties": {"mode": {"type": "string", "enum": ["none", "low", "high"], "default": "none"}}},
            },
        },
        "response_format": {
            "type": "object",
            "properties": {
                "type": {"type": "string", "enum": ["json_schema"]},
                "json_schema": {
                    "type": "object",
                    "required": ["name"],
                    "properties": {
                        "name": {"type": "string", "maxLength": 64},
                        "description": {"type": "string"},
                        "schema": {"type": "object"},
                        "strict": {"type": "boolean", "default": False},
                    },
                },
            },
        },
    },
    notes=["The path is OpenAI-shaped but the documented body is Reka-specific; the key rides on X-Api-Key, not a bearer"],
)

BUILD["huggingface.oai"] = schema(
    "Hugging Face Inference Providers chat completion request",
    "https://huggingface.co/docs/inference-providers/tasks/chat-completion",
    ["messages"],
    {
        "model": {"type": "string"},
        "messages": MESSAGES,
        "frequency_penalty": {"type": "number", "minimum": -2, "maximum": 2},
        "presence_penalty": {"type": "number", "minimum": -2, "maximum": 2},
        "logprobs": {"type": "boolean"},
        "top_logprobs": {"type": "integer", "minimum": 0, "maximum": 5},
        "max_tokens": {"type": "integer"},
        "reasoning_effort": {"type": "string"},
        "response_format": {"type": "object"},
        "seed": {"type": "integer"},
        "stop": {"type": "array", "items": {"type": "string"}, "maxItems": 4},
        "stream": {"type": "boolean"},
        "stream_options": STREAM_OPTIONS,
        "temperature": {"type": "number", "minimum": 0, "maximum": 2},
        "top_p": {"type": "number"},
        "tools": TOOLS,
        "tool_choice": TOOL_CHOICE,
        "tool_prompt": {"type": "string"},
    },
    notes=[
        "The model id carries a provider selection policy suffix: :fastest, :cheapest, :preferred, or an explicit provider name",
        "reasoning_effort support and defaults are provider and model dependent",
    ],
)

for name, doc in BUILD.items():
    provider, ingress = name.split(".")
    write_schema(OUT / f"{ingress}.{provider}.request.json", doc)
    print(f"{ingress}.{provider}.request: props={len(doc['properties'])} required={doc['required']}")

print("\nwrote", len(BUILD), "documentation-derived schemas")
