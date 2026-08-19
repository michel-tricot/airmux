"""Run endpoint-specific behavioral probes for every catalogued model.

    uv run python probe_capabilities.py
    uv run python probe_capabilities.py openai groq
    uv run python probe_capabilities.py --probe=json_schema --limit=5

Successful protocol behavior and explicit unsupported errors are conclusive. Authentication,
access, throttling, timeouts and generic bad requests remain unknown. Every attempt is stored,
and conclusive live evidence overrides model-listing metadata when taxonomy.yml is built.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import binascii
import hashlib
import json
import os
import re
import ssl
import struct
import sys
import urllib.error
import urllib.request
import zlib
from pathlib import Path

import yaml
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent))
from canonical import write_catalog
from capability_support import PROBES
from evidence import CAPABILITY_PROBE_VERSION, current_targets, merge_live_evidence
from paths import ENV_FILE, TAXONOMY
from probe_runtime import ProbeOutcome, ProbeReportEntry, Support, http_outcome, write_probe_report
from provider_profile import endpoints, inference_headers, inference_url, provider_id, select_provider_ids

CTX = ssl.create_default_context()
TIMEOUT = 90
MAX_TOKENS = 64
CONCURRENCY = 4
JSON_SCHEMA = {
    "type": "object",
    "properties": {"answer": {"type": "integer", "const": 42}},
    "required": ["answer"],
    "additionalProperties": False,
}


def _png_chunk(kind: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", binascii.crc32(kind + data) & 0xFFFFFFFF)


def image_challenge(model_id: str) -> tuple[str, str, str]:
    colors = {
        "red": b"\xff\x00\x00",
        "blue": b"\x00\x00\xff",
        "green": b"\x00\x80\x00",
        "yellow": b"\xff\xff\x00",
    }
    ordered = sorted(colors, key=lambda name: hashlib.sha256(f"{model_id}:{name}".encode()).digest())
    width, height = 160, 64
    scanline = b"".join(colors[name] * (width // len(ordered)) for name in ordered)
    pixels = b"".join(b"\x00" + scanline for _ in range(height))
    png = b"\x89PNG\r\n\x1a\n" + _png_chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
    png += _png_chunk(b"IDAT", zlib.compress(pixels)) + _png_chunk(b"IEND", b"")
    url = "data:image/png;base64," + base64.b64encode(png).decode()
    prompt = "List the four vertical band colors from left to right using only: red blue green yellow."
    return url, prompt, " ".join(ordered)


SINGLE_TOOL = {
    "name": "report_result",
    "description": "Report the requested result",
    "parameters": {
        "type": "object",
        "properties": {"value": {"type": "string"}},
        "required": ["value"],
        "additionalProperties": False,
    },
}
PARALLEL_TOOLS = [
    {
        "name": name,
        "description": f"Report {name.removeprefix('report_')}",
        "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
    }
    for name in ("report_alpha", "report_beta")
]


def _base(endpoint: str, model_id: str, prompt: object, provider_id: str | None) -> dict:
    if endpoint == "responses":
        return {"model": model_id, "input": prompt, "max_output_tokens": MAX_TOKENS, "store": False}
    if endpoint == "messages":
        return {"model": model_id, "messages": [{"role": "user", "content": prompt}], "max_tokens": MAX_TOKENS}
    output_limit = {"max_completion_tokens": MAX_TOKENS} if provider_id == "openai" else {"max_tokens": MAX_TOKENS}
    return {"model": model_id, "messages": [{"role": "user", "content": prompt}], **output_limit}


def _image_body(endpoint: str, model_id: str, provider_id: str | None) -> dict:
    image_url, prompt, _ = image_challenge(model_id)
    if endpoint == "responses":
        content = [{"type": "input_text", "text": prompt}, {"type": "input_image", "image_url": image_url, "detail": "low"}]
        return _base(endpoint, model_id, [{"type": "message", "role": "user", "content": content}], provider_id)
    if endpoint == "messages":
        content = [
            {"type": "text", "text": prompt},
            {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": image_url.split(",", 1)[1]}},
        ]
        return _base(endpoint, model_id, content, provider_id)
    content = [{"type": "text", "text": prompt}, {"type": "image_url", "image_url": {"url": image_url, "detail": "low"}}]
    return _base(endpoint, model_id, content, provider_id)


def _tool_body(endpoint: str, model_id: str, provider_id: str | None, parallel: bool) -> dict:
    tools = PARALLEL_TOOLS if parallel else [SINGLE_TOOL]
    prompt = "Call report_alpha and report_beta once each. Do not answer with text." if parallel else "Call report_result with value ok."
    body = _base(endpoint, model_id, prompt, provider_id)
    if endpoint == "responses":
        choice: object = "required" if parallel else {"type": "function", "name": SINGLE_TOOL["name"]}
        return {**body, "tools": [{"type": "function", **tool} for tool in tools], "tool_choice": choice, "parallel_tool_calls": parallel}
    if endpoint == "messages":
        anthropic_tools = [{"name": tool["name"], "description": tool["description"], "input_schema": tool["parameters"]} for tool in tools]
        choice = {"type": "any"} if parallel else {"type": "tool", "name": SINGLE_TOOL["name"]}
        return {**body, "tools": anthropic_tools, "tool_choice": choice}
    openai_tools = [{"type": "function", "function": tool} for tool in tools]
    choice = "required" if parallel else {"type": "function", "function": {"name": SINGLE_TOOL["name"]}}
    return {**body, "tools": openai_tools, "tool_choice": choice}


def _json_body(endpoint: str, model_id: str, provider_id: str | None, schema: bool) -> dict:
    body = _base(endpoint, model_id, "Return a JSON object with the single property answer set to the number 42.", provider_id)
    if endpoint == "responses":
        output_format = {"type": "json_schema", "name": "probe", "strict": True, "schema": JSON_SCHEMA} if schema else {"type": "json_object"}
        return {**body, "text": {"format": output_format}}
    if endpoint == "messages":
        if schema:
            return {**body, "output_config": {"format": {"type": "json_schema", "schema": JSON_SCHEMA}}}
        return {**body, "response_format": {"type": "json_object"}}
    response_format = (
        {"type": "json_schema", "json_schema": {"name": "probe", "strict": True, "schema": JSON_SCHEMA}} if schema else {"type": "json_object"}
    )
    return {**body, "response_format": response_format}


def _reasoning_body(endpoint: str, model_id: str, provider_id: str | None) -> dict:
    body = _base(endpoint, model_id, "Reason briefly, then answer: what is 20 plus 22?", provider_id)
    if endpoint == "responses":
        return {**body, "reasoning": {"effort": "low", "summary": "auto"}, "include": ["reasoning.encrypted_content"]}
    if endpoint == "messages":
        return {**body, "max_tokens": 1100, "thinking": {"type": "enabled", "budget_tokens": 1024}}
    return body


def request_body(endpoint: str, model_id: str, probe_name: str, provider_id: str | None = None) -> dict:
    if probe_name == "streaming":
        return {**_base(endpoint, model_id, "say ok", provider_id), "stream": True}
    if probe_name == "image_input":
        return _image_body(endpoint, model_id, provider_id)
    if probe_name == "tools":
        return _tool_body(endpoint, model_id, provider_id, False)
    if probe_name == "parallel_tools":
        return _tool_body(endpoint, model_id, provider_id, True)
    if probe_name == "json_object":
        return _json_body(endpoint, model_id, provider_id, False)
    if probe_name == "json_schema":
        return _json_body(endpoint, model_id, provider_id, True)
    if probe_name == "reasoning":
        return _reasoning_body(endpoint, model_id, provider_id)
    raise ValueError(probe_name)


def _payload(body: str) -> dict:
    try:
        value = json.loads(body)
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def _text(payload: dict) -> str:
    if isinstance(payload.get("output_text"), str):
        return payload["output_text"]
    content = payload.get("content") or []
    if isinstance(content, list):
        text = "".join(block.get("text", "") for block in content if isinstance(block, dict))
        if text:
            return text
    output = payload.get("output") or []
    text = "".join(
        block.get("text", "") for item in output if isinstance(item, dict) for block in item.get("content") or [] if isinstance(block, dict)
    )
    if text:
        return text
    choices = payload.get("choices") or []
    message = choices[0].get("message") or {} if choices and isinstance(choices[0], dict) else {}
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(part.get("text", "") for part in content if isinstance(part, dict))
    return ""


def _tool_names(payload: dict) -> list[str]:
    content = payload.get("content") or []
    names = [block.get("name", "") for block in content if isinstance(block, dict) and block.get("type") == "tool_use"]
    output = payload.get("output") or []
    names.extend(item.get("name", "") for item in output if isinstance(item, dict) and item.get("type") == "function_call")
    choices = payload.get("choices") or []
    message = choices[0].get("message") or {} if choices and isinstance(choices[0], dict) else {}
    names.extend((call.get("function") or {}).get("name", "") for call in message.get("tool_calls") or [] if isinstance(call, dict))
    return names


def _reasoning_text(payload: dict) -> str:
    content = payload.get("content") or []
    text = "".join(block.get("thinking", "") for block in content if isinstance(block, dict) and block.get("type") == "thinking")
    output = payload.get("output") or []
    text += "".join(
        summary.get("text", "")
        for item in output
        if isinstance(item, dict) and item.get("type") == "reasoning"
        for summary in item.get("summary") or []
        if isinstance(summary, dict)
    )
    choices = payload.get("choices") or []
    message = choices[0].get("message") or {} if choices and isinstance(choices[0], dict) else {}
    return text + str(message.get("reasoning_content") or message.get("reasoning") or "")


def _has_reasoning(payload: dict) -> bool:
    content = payload.get("content") or []
    if any(isinstance(block, dict) and block.get("type") == "thinking" for block in content):
        return True
    output = payload.get("output") or []
    if any(isinstance(item, dict) and item.get("type") == "reasoning" for item in output):
        return True
    choices = payload.get("choices") or []
    message = choices[0].get("message") or {} if choices and isinstance(choices[0], dict) else {}
    return bool(message.get("reasoning_content"))


def _valid_json(text: str, schema: bool) -> bool:
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        return False
    if not isinstance(value, dict):
        return False
    return not schema or value == {"answer": 42}


def _image_answer(text: str) -> str:
    return " ".join(re.findall(r"\b(?:red|blue|green|yellow)\b", text.casefold()))


def _successful_result(probe_name: str, content_type: str, body: str, expected: str | None) -> Support | None:
    if probe_name == "streaming":
        supported = content_type.startswith("text/event-stream") and re.search(r"(?m)^data:", body) is not None
        return "supported" if supported else None
    payload = _payload(body)
    if probe_name == "image_input":
        answer = _image_answer(_text(payload) + " " + _reasoning_text(payload))
        if expected is not None and answer == expected:
            return "supported"
        return None
    if probe_name == "tools":
        if "report_result" in _tool_names(payload):
            return "supported"
        return None
    if probe_name == "parallel_tools":
        if {"report_alpha", "report_beta"} <= set(_tool_names(payload)):
            return "supported"
        return None
    if probe_name in {"json_object", "json_schema"}:
        if _valid_json(_text(payload), probe_name == "json_schema"):
            return "supported"
        return None
    if _has_reasoning(payload):
        return "supported"
    return None


def classify_response(probe_name: str, status: int, content_type: str, body: str, expected: str | None = None) -> Support | None:
    if 200 <= status < 300:
        return _successful_result(probe_name, content_type, body, expected)
    if status not in {400, 404, 422}:
        return None
    payload = _payload(body)
    error = payload.get("error")
    message = str(error.get("message") if isinstance(error, dict) else error or payload or body).casefold()
    terms = {
        "streaming": ("stream",),
        "image_input": ("image", "vision", "multimodal"),
        "tools": ("tool", "function"),
        "parallel_tools": ("parallel", "tool", "function"),
        "json_object": ("json", "response_format", "response format"),
        "json_schema": ("json", "schema", "response_format", "output_config"),
        "reasoning": ("reasoning", "thinking"),
    }[probe_name]
    rejected = any(phrase in message for phrase in ("not support", "unsupported", "does not accept", "only supports"))
    return "unsupported" if rejected and any(term in message for term in terms) else None


def _headers(provider: dict, endpoint: str, key: str) -> dict[str, str]:
    headers = {"Content-Type": "application/json", "User-Agent": "airllm-capability-probe/1.0", "Accept": "application/json"}
    return {**headers, **inference_headers(provider, endpoint, key)}


def _detail(body: str) -> str:
    return " ".join(body.split())[:200]


def probe(provider: dict, model_id: str, endpoint: str, probe_name: str, key: str) -> ProbeOutcome:
    headers = _headers(provider, endpoint, key)
    if probe_name == "streaming":
        headers["Accept"] = "text/event-stream"
    request = urllib.request.Request(
        inference_url(provider, endpoint),
        data=json.dumps(request_body(endpoint, model_id, probe_name, provider_id(provider))).encode(),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT, context=CTX) as response:
            expected = image_challenge(model_id)[2] if probe_name == "image_input" else None
            body = response.read().decode(errors="replace")
            support = classify_response(probe_name, response.status, response.headers.get("Content-Type", ""), body, expected)
            return http_outcome(response.status, support, _detail(body))
    except urllib.error.HTTPError as exc:
        expected = image_challenge(model_id)[2] if probe_name == "image_input" else None
        body = exc.read().decode(errors="replace")
        support = classify_response(probe_name, exc.code, exc.headers.get("Content-Type", ""), body, expected)
        return http_outcome(exc.code, support, _detail(body))
    except TimeoutError:
        return ProbeOutcome(None, "timeout")
    except OSError as exc:
        return ProbeOutcome(None, "transport_error", type(exc).__name__)


def _record(provider: dict, model: dict, attempts: dict[str, list[str]], support: dict[str, dict[str, Support]], replace: bool = False) -> None:
    evidence = dict(model.get("capability_evidence") or {})
    targets = current_targets(provider, model, endpoints(provider), "capabilities", CAPABILITY_PROBE_VERSION)
    evidence["live_probe"] = merge_live_evidence(evidence.get("live_probe") or {}, attempts, support, targets, CAPABILITY_PROBE_VERSION, replace)
    model["capability_evidence"] = evidence


def probe_models(provider: dict, models: list[dict], key: str, probe_filter: str | None = None, replace: bool = False) -> tuple[int, int]:
    selected = sorted(probe_name for probe_name in PROBES if probe_filter is None or probe_name == probe_filter)
    attempted = 0
    conclusive = 0
    for model in models:
        attempts: dict[str, list[str]] = {}
        support: dict[str, dict[str, Support]] = {}
        for endpoint in endpoints(provider):
            attempts[endpoint] = selected
            endpoint_support: dict[str, Support] = {}
            for probe_name in selected:
                outcome = probe(provider, model.get("upstream_id") or model["id"], endpoint, probe_name, key)
                if outcome.support is not None:
                    endpoint_support[probe_name] = outcome.support
            if endpoint_support:
                support[endpoint] = endpoint_support
            attempted += len(selected)
            conclusive += len(endpoint_support)
        _record(provider, model, attempts, support, replace)
    return attempted, conclusive


async def _probe_catalog(
    provider: dict, models: list[dict], key: str, probe_filter: str | None, replace: bool
) -> tuple[int, int, list[ProbeReportEntry]]:
    semaphore = asyncio.Semaphore(CONCURRENCY)
    selected = sorted(probe_name for probe_name in PROBES if probe_filter is None or probe_name == probe_filter)
    plans = [(model, endpoint, probe_name) for model in models for endpoint in endpoints(provider) for probe_name in selected]

    async def one(model: dict, endpoint: str, probe_name: str) -> tuple[dict, str, str, ProbeOutcome]:
        async with semaphore:
            outcome = await asyncio.to_thread(probe, provider, model.get("upstream_id") or model["id"], endpoint, probe_name, key)
        print({"supported": ".", "unsupported": "-", None: "?"}[outcome.support], end="", flush=True)
        return model, endpoint, probe_name, outcome

    results = await asyncio.gather(*(one(*plan) for plan in plans))
    grouped: dict[int, tuple[dict, dict[str, list[str]], dict[str, dict[str, Support]]]] = {}
    report = []
    for model, endpoint, probe_name, outcome in results:
        _, attempts, support = grouped.setdefault(id(model), (model, {}, {}))
        attempts.setdefault(endpoint, []).append(probe_name)
        if outcome.support is not None:
            support.setdefault(endpoint, {})[probe_name] = outcome.support
        report.append(ProbeReportEntry(provider_id(provider), model["id"], endpoint, probe_name, outcome.support, outcome.reason, outcome.detail))
    for model, attempts, support in grouped.values():
        _record(provider, model, attempts, support, replace)
    return len(results), sum(outcome.support is not None for *_, outcome in results), report


def _selected_probes(probe_filter: str | None) -> list[str]:
    return sorted(probe_name for probe_name in PROBES if probe_filter is None or probe_name == probe_filter)


def _catalog_jobs(wanted: set[str], limit: int | None) -> tuple[list[tuple[Path, dict, dict, list[dict], str]], list[str]]:
    providers = {provider["id"]: provider for provider in yaml.safe_load((TAXONOMY / "providers.yml").read_text())["providers"]}
    selected_ids = select_provider_ids(wanted, set(providers))
    jobs: list[tuple[Path, dict, dict, list[dict], str]] = []
    missing_credentials = []
    for path in sorted((TAXONOMY / "models").glob("*.json")):
        catalog = json.loads(path.read_text())
        provider = providers.get(catalog["provider"])
        if provider is None or provider["id"] not in selected_ids:
            continue
        key = os.environ.get(provider["env_var"])
        if not key:
            missing_credentials.append(f"{provider['id']}: no {provider['env_var']}")
            continue
        jobs.append((path, catalog, provider, catalog["models"][:limit], key))
    return jobs, missing_credentials


async def run(
    wanted: set[str],
    probe_filter: str | None,
    limit: int | None,
    replace: bool,
    *,
    allow_empty: bool = False,
    allow_missing_credentials: bool = False,
    confirmed: bool = False,
    max_requests: int = 500,
) -> tuple[int, int, int]:
    catalog_jobs, missing_credentials = _catalog_jobs(wanted, limit)
    if missing_credentials and not allow_missing_credentials:
        raise RuntimeError("missing credentials: " + "; ".join(missing_credentials))
    selected = _selected_probes(probe_filter)
    planned = sum(len(models) * len(endpoints(provider)) * len(selected) for _, _, provider, models, _ in catalog_jobs)
    if planned == 0 and not allow_empty:
        raise RuntimeError("the selected capability probe run schedules zero requests")
    if planned > max_requests and not confirmed:
        raise RuntimeError(f"the run schedules {planned} requests; pass --yes or lower the scope below --max-requests={max_requests}")
    jobs = [(provider_id(provider), _probe_catalog(provider, models, key, probe_filter, replace)) for _, _, provider, models, key in catalog_jobs]
    results = await asyncio.gather(*(job for _, job in jobs))
    print()
    for (selected_provider_id, _), (attempted, conclusive, _) in zip(jobs, results, strict=True):
        print(f"  {selected_provider_id:<11} {conclusive:>4}/{attempted:<4} conclusive")
    changed = sum(write_catalog(path, catalog) for path, catalog, _, _, _ in catalog_jobs)
    report = [entry for _, _, entries in results for entry in entries]
    write_probe_report(TAXONOMY / "reports" / "capability-probes.json", report)
    return sum(result[0] for result in results), sum(result[1] for result in results), changed


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Probe observable model capabilities")
    parser.add_argument("providers", nargs="*", help="Provider ids; defaults to every active provider")
    parser.add_argument("--probe", choices=sorted(PROBES))
    parser.add_argument("--limit", type=int)
    parser.add_argument("--replace", action="store_true", help="Discard evidence from earlier probe versions")
    parser.add_argument("--yes", action="store_true", help="Confirm a run above the request guardrail")
    parser.add_argument("--max-requests", type=int, default=500)
    parser.add_argument("--allow-empty", action="store_true")
    parser.add_argument("--allow-missing-credentials", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    arguments = parser.parse_args(argv)
    if arguments.limit is not None and arguments.limit < 1:
        parser.error("--limit must be positive")
    if arguments.max_requests < 1:
        parser.error("--max-requests must be positive")
    if arguments.replace and (arguments.probe is not None or arguments.limit is not None):
        parser.error("--replace requires a complete, unfiltered run")
    return arguments


def main() -> int:
    arguments = parse_args()
    load_dotenv(ENV_FILE)
    try:
        catalog_jobs, missing_credentials = _catalog_jobs(set(arguments.providers), arguments.limit)
        planned = sum(len(models) * len(endpoints(provider)) * len(_selected_probes(arguments.probe)) for _, _, provider, models, _ in catalog_jobs)
        print(f"planned capability requests: {planned}")
        for missing in missing_credentials:
            print(f"  missing {missing}")
        if arguments.dry_run:
            if missing_credentials and not arguments.allow_missing_credentials:
                return 2
            return 0 if planned or arguments.allow_empty else 1
        attempted, conclusive, changed = asyncio.run(
            run(
                set(arguments.providers),
                arguments.probe,
                arguments.limit,
                arguments.replace,
                allow_empty=arguments.allow_empty,
                allow_missing_credentials=arguments.allow_missing_credentials,
                confirmed=arguments.yes,
                max_requests=arguments.max_requests,
            )
        )
    except (RuntimeError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(f"{attempted} behavioral probes attempted; {conclusive} conclusive; {changed} catalogs changed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
