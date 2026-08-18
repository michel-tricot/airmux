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
    body = {"model": model_id, "messages": [{"role": "user", "content": "say ok"}], "max_completion_tokens": MAX_TOKENS}
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


def main() -> int:
    wanted = {argument for argument in sys.argv[1:] if not argument.startswith("--")}
    parameter_filter = next((argument.split("=", 1)[1] for argument in sys.argv[1:] if argument.startswith("--parameter=")), None)
    limit = next((int(argument.split("=", 1)[1]) for argument in sys.argv[1:] if argument.startswith("--limit=")), None)
    providers = {provider["id"]: provider for provider in yaml.safe_load((TAXONOMY / "providers.yml").read_text())["providers"]}
    changed = 0
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
        for model in catalog["models"][:limit]:
            if model.get("reachable") is False:
                continue
            support: dict[str, dict[str, str]] = {}
            for endpoint in endpoints(provider):
                endpoint_support = {
                    parameter: status
                    for parameter, value in PROBES[endpoint].items()
                    if (parameter_filter is None or parameter == parameter_filter)
                    and (status := probe(provider, model.get("upstream_id") or model["id"], endpoint, parameter, value, key)) is not None
                }
                if endpoint_support:
                    support[endpoint] = endpoint_support
                    conclusive += len(endpoint_support)
            if support:
                parameter_evidence = dict(model.get("parameter_evidence") or {})
                previous = ((parameter_evidence.get("live_probe") or {}).get("support") or {})
                parameter_evidence["live_probe"] = {
                    "support": {
                        endpoint: {**(previous.get(endpoint) or {}), **statuses}
                        for endpoint, statuses in {**previous, **support}.items()
                    }
                }
                model["parameter_evidence"] = parameter_evidence
        changed += write_catalog(path, catalog)
    print(f"{conclusive} conclusive parameter probes; {changed} catalogs changed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
