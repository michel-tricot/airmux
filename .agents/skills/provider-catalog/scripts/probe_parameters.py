from __future__ import annotations

import json
import os
import ssl
import sys
import urllib.error
import urllib.request
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from canonical import write_catalog
from parameter_support import classify_parameter_response
from paths import TAXONOMY

CTX = ssl.create_default_context()
TIMEOUT = 60
MAX_TOKENS = 16
PROBES = {
    "chat/completions": {
        "temperature": 1.0,
        "top_p": 0.9,
        "seed": 1,
        "stop": ["END"],
        "reasoning_effort": "medium",
        "parallel_tool_calls": False,
        "logprobs": True,
    },
    "responses": {
        "temperature": 1.0,
        "top_p": 0.9,
        "reasoning_effort": "medium",
        "parallel_tool_calls": False,
        "logprobs": True,
    },
    "messages": {
        "temperature": 1.0,
        "top_p": 0.9,
        "stop": ["END"],
    },
}


def request_body(endpoint: str, model_id: str, parameter: str, value: object) -> dict:
    if endpoint == "responses":
        body = {"model": model_id, "input": "say ok", "max_output_tokens": MAX_TOKENS, "store": False}
        if parameter == "reasoning_effort":
            return {**body, "reasoning": {"effort": value}}
        return {**body, parameter: value}
    if endpoint == "messages":
        body = {"model": model_id, "messages": [{"role": "user", "content": "say ok"}], "max_tokens": MAX_TOKENS}
        spelling = "stop_sequences" if parameter == "stop" else parameter
        return {**body, spelling: value}
    body = {"model": model_id, "messages": [{"role": "user", "content": "say ok"}]}
    return {**body, parameter: value}


def probe(provider: dict, model_id: str, endpoint: str, parameter: str, value: object, key: str) -> str | None:
    url = f"{provider['base_url'].rstrip('/')}/{endpoint}"
    headers = {"Content-Type": "application/json", "User-Agent": "airllm-parameter-probe/1.0", "Accept": "application/json"}
    if endpoint == "messages":
        headers["x-api-key"] = key
        headers["anthropic-version"] = "2023-06-01"
    else:
        headers["Authorization"] = f"Bearer {key}"
    request = urllib.request.Request(url, data=json.dumps(request_body(endpoint, model_id, parameter, value)).encode(), headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT, context=CTX) as response:
            return classify_parameter_response(response.status, response.read().decode(), parameter)
    except urllib.error.HTTPError as exc:
        return classify_parameter_response(exc.code, exc.read().decode(), parameter)
    except (TimeoutError, OSError):
        return None


def endpoints(provider: dict) -> tuple[str, ...]:
    selected = []
    if "oai" in provider["ingress"]:
        selected.append("chat/completions")
    if "oai_responses" in provider["ingress"]:
        selected.append("responses")
    if "anthropic" in provider["ingress"]:
        selected.append("messages")
    return tuple(selected)


def probe_models(provider: dict, models: list[dict], key: str, parameter_filter: str | None = None) -> tuple[int, int]:
    attempted = 0
    conclusive = 0
    for model in models:
        support: dict[str, dict[str, str]] = {}
        attempts: dict[str, list[str]] = {}
        for endpoint in endpoints(provider):
            selected = {parameter: value for parameter, value in PROBES[endpoint].items() if parameter_filter is None or parameter == parameter_filter}
            endpoint_support = {
                parameter: status
                for parameter, value in selected.items()
                if (status := probe(provider, model.get("upstream_id") or model["id"], endpoint, parameter, value, key)) is not None
            }
            if selected:
                attempts[endpoint] = sorted(selected)
                attempted += len(selected)
            if endpoint_support:
                support[endpoint] = endpoint_support
                conclusive += len(endpoint_support)
        if not attempts:
            continue
        parameter_evidence = dict(model.get("parameter_evidence") or {})
        previous_probe = parameter_evidence.get("live_probe") or {}
        previous_support = previous_probe.get("support") or {}
        previous_attempts = previous_probe.get("attempted") or {}
        parameter_evidence["live_probe"] = {
            "attempted": {
                endpoint: sorted(set(previous_attempts.get(endpoint) or []) | set(parameters))
                for endpoint, parameters in {**previous_attempts, **attempts}.items()
            },
            "support": {
                endpoint: {**(previous_support.get(endpoint) or {}), **statuses}
                for endpoint, statuses in {**previous_support, **support}.items()
            },
        }
        model["parameter_evidence"] = parameter_evidence
    return attempted, conclusive


def main() -> int:
    wanted = {argument for argument in sys.argv[1:] if not argument.startswith("--")}
    parameter_filter = next((argument.split("=", 1)[1] for argument in sys.argv[1:] if argument.startswith("--parameter=")), None)
    limit = next((int(argument.split("=", 1)[1]) for argument in sys.argv[1:] if argument.startswith("--limit=")), None)
    providers = {provider["id"]: provider for provider in yaml.safe_load((TAXONOMY / "providers.yml").read_text())["providers"]}
    changed = 0
    attempted = 0
    conclusive = 0
    for path in sorted((TAXONOMY / "models").glob("*.json")):
        catalog = json.loads(path.read_text())
        provider = providers[catalog["provider"]]
        if wanted and provider["id"] not in wanted:
            continue
        key = os.environ.get(provider["env_var"])
        if not key:
            print(f"skip {provider['id']}: no {provider['env_var']}")
            continue
        models = [model for model in catalog["models"] if model.get("reachable") is not False][:limit]
        model_attempted, model_conclusive = probe_models(provider, models, key, parameter_filter)
        attempted += model_attempted
        conclusive += model_conclusive
        changed += write_catalog(path, catalog)
    print(f"{attempted} parameter probes attempted; {conclusive} conclusive; {changed} catalogs changed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
