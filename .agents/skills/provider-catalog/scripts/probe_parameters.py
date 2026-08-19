from __future__ import annotations

import argparse
import asyncio
import json
import os
import ssl
import sys
import urllib.error
import urllib.request
from pathlib import Path

import yaml
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent))
from canonical import write_catalog
from evidence import PARAMETER_PROBE_VERSION, current_targets, merge_live_evidence
from parameter_support import classify_parameter_response
from paths import ENV_FILE, TAXONOMY
from probe_runtime import ProbeOutcome, ProbeReportEntry, Support, http_outcome, write_probe_report
from provider_profile import endpoints, inference_headers, inference_url, provider_id, select_provider_ids

CTX = ssl.create_default_context()
TIMEOUT = 60
MAX_TOKENS = 16
CONCURRENCY = 4
PARAMETER_TOOL: dict[str, object] = {
    "type": "function",
    "function": {
        "name": "report_result",
        "description": "Report the result",
        "parameters": {
            "type": "object",
            "properties": {"value": {"type": "string"}},
            "required": ["value"],
            "additionalProperties": False,
        },
    },
}
PROBES = {
    "chat/completions": {
        "temperature": 0.7,
        "top_p": 0.9,
        "seed": 1,
        "stop": ["END"],
        "reasoning_effort": "medium",
        "parallel_tool_calls": False,
        "logprobs": True,
    },
    "responses": {
        "temperature": 0.7,
        "top_p": 0.9,
        "reasoning_effort": "medium",
        "parallel_tool_calls": False,
        "logprobs": True,
    },
    "messages": {
        "temperature": 0.7,
        "top_p": 0.9,
        "stop": ["END"],
    },
}


def request_body(endpoint: str, model_id: str, parameter: str, value: object) -> dict:
    if endpoint == "responses":
        body = {"model": model_id, "input": "say ok", "max_output_tokens": MAX_TOKENS, "store": False}
        if parameter == "reasoning_effort":
            return {**body, "reasoning": {"effort": value}}
        if parameter == "parallel_tool_calls":
            function = PARAMETER_TOOL["function"]
            if not isinstance(function, dict):
                raise RuntimeError("parameter tool definition is invalid")
            return {**body, "tools": [{"type": "function", **function}], parameter: value}
        return {**body, parameter: value}
    if endpoint == "messages":
        body = {"model": model_id, "messages": [{"role": "user", "content": "say ok"}], "max_tokens": MAX_TOKENS}
        spelling = "stop_sequences" if parameter == "stop" else parameter
        return {**body, spelling: value}
    body = {"model": model_id, "messages": [{"role": "user", "content": "say ok"}]}
    if parameter == "parallel_tool_calls":
        return {**body, "tools": [PARAMETER_TOOL], parameter: value}
    return {**body, parameter: value}


def probe(provider: dict, model_id: str, endpoint: str, parameter: str, value: object, key: str) -> ProbeOutcome:
    headers = {"Content-Type": "application/json", "User-Agent": "airllm-parameter-probe/1.0", "Accept": "application/json"}
    headers.update(inference_headers(provider, endpoint, key))
    request = urllib.request.Request(
        inference_url(provider, endpoint),
        data=json.dumps(request_body(endpoint, model_id, parameter, value)).encode(),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT, context=CTX) as response:
            body = response.read().decode(errors="replace")
            return http_outcome(response.status, classify_parameter_response(response.status, body, parameter), " ".join(body.split())[:200])
    except urllib.error.HTTPError as exc:
        body = exc.read().decode(errors="replace")
        return http_outcome(exc.code, classify_parameter_response(exc.code, body, parameter), " ".join(body.split())[:200])
    except TimeoutError:
        return ProbeOutcome(None, "timeout")
    except OSError as exc:
        return ProbeOutcome(None, "transport_error", type(exc).__name__)


def _record(provider: dict, model: dict, attempts: dict[str, list[str]], support: dict[str, dict[str, Support]], replace: bool = False) -> None:
    parameter_evidence = dict(model.get("parameter_evidence") or {})
    targets = current_targets(provider, model, endpoints(provider), "parameters", PARAMETER_PROBE_VERSION)
    parameter_evidence["live_probe"] = merge_live_evidence(
        parameter_evidence.get("live_probe") or {}, attempts, support, targets, PARAMETER_PROBE_VERSION, replace
    )
    model["parameter_evidence"] = parameter_evidence


def probe_models(
    provider: dict,
    models: list[dict],
    key: str,
    parameter_filter: str | None = None,
    replace: bool = False,
) -> tuple[int, int]:
    attempted = 0
    conclusive = 0
    for model in models:
        support: dict[str, dict[str, Support]] = {}
        attempts: dict[str, list[str]] = {}
        for endpoint in endpoints(provider):
            selected = {
                parameter: value for parameter, value in PROBES[endpoint].items() if parameter_filter is None or parameter == parameter_filter
            }
            endpoint_support: dict[str, Support] = {}
            for parameter, value in selected.items():
                outcome = probe(provider, model.get("upstream_id") or model["id"], endpoint, parameter, value, key)
                if outcome.support is not None:
                    endpoint_support[parameter] = outcome.support
            if selected:
                attempts[endpoint] = sorted(selected)
                attempted += len(selected)
            if endpoint_support:
                support[endpoint] = endpoint_support
                conclusive += len(endpoint_support)
        if not attempts:
            continue
        _record(provider, model, attempts, support, replace)
    return attempted, conclusive


async def _probe_catalog(
    provider: dict,
    models: list[dict],
    key: str,
    parameter_filter: str | None,
    replace: bool,
) -> tuple[int, int, list[ProbeReportEntry]]:
    semaphore = asyncio.Semaphore(CONCURRENCY)
    plans = [
        (model, endpoint, parameter, value)
        for model in models
        for endpoint in endpoints(provider)
        for parameter, value in PROBES[endpoint].items()
        if parameter_filter is None or parameter == parameter_filter
    ]

    async def one(model: dict, endpoint: str, parameter: str, value: object) -> tuple[dict, str, str, ProbeOutcome]:
        async with semaphore:
            outcome = await asyncio.to_thread(
                probe,
                provider,
                model.get("upstream_id") or model["id"],
                endpoint,
                parameter,
                value,
                key,
            )
        print({"supported": ".", "unsupported": "-", None: "?"}[outcome.support], end="", flush=True)
        return model, endpoint, parameter, outcome

    results = await asyncio.gather(*(one(*plan) for plan in plans))
    grouped: dict[int, tuple[dict, dict[str, list[str]], dict[str, dict[str, Support]]]] = {}
    report = []
    for model, endpoint, parameter, outcome in results:
        _, attempts, support = grouped.setdefault(id(model), (model, {}, {}))
        attempts.setdefault(endpoint, []).append(parameter)
        if outcome.support is not None:
            support.setdefault(endpoint, {})[parameter] = outcome.support
        report.append(ProbeReportEntry(provider_id(provider), model["id"], endpoint, parameter, outcome.support, outcome.reason, outcome.detail))
    for model, attempts, support in grouped.values():
        _record(provider, model, attempts, support, replace)
    return len(results), sum(outcome.support is not None for *_, outcome in results), report


def _catalog_jobs(wanted: set[str], limit: int | None) -> tuple[list[tuple[Path, dict, dict, list[dict], str]], list[str]]:
    providers = {provider["id"]: provider for provider in yaml.safe_load((TAXONOMY / "providers.yml").read_text())["providers"]}
    selected_ids = select_provider_ids(wanted, set(providers))
    jobs = []
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
        models = catalog["models"][:limit]
        jobs.append((path, catalog, provider, models, key))
    return jobs, missing_credentials


def _planned_requests(catalog_jobs: list[tuple[Path, dict, dict, list[dict], str]], parameter_filter: str | None) -> int:
    return sum(
        len(models)
        * sum(sum(parameter_filter is None or parameter == parameter_filter for parameter in PROBES[endpoint]) for endpoint in endpoints(provider))
        for _, _, provider, models, _ in catalog_jobs
    )


async def run(
    wanted: set[str],
    parameter_filter: str | None,
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
    planned = _planned_requests(catalog_jobs, parameter_filter)
    if planned == 0 and not allow_empty:
        raise RuntimeError("the selected parameter probe run schedules zero requests")
    if planned > max_requests and not confirmed:
        raise RuntimeError(f"the run schedules {planned} requests; pass --yes or lower the scope below --max-requests={max_requests}")
    jobs = [(provider_id(provider), _probe_catalog(provider, models, key, parameter_filter, replace)) for _, _, provider, models, key in catalog_jobs]
    results = await asyncio.gather(*(job for _, job in jobs))
    print()
    for (selected_provider_id, _), (attempted, conclusive, _) in zip(jobs, results, strict=True):
        print(f"  {selected_provider_id:<11} {conclusive:>4}/{attempted:<4} conclusive")
    changed = sum(write_catalog(path, catalog) for path, catalog, _, _, _ in catalog_jobs)
    entries = [entry for _, _, report in results for entry in report]
    write_probe_report(TAXONOMY / "reports" / "parameter-probes.json", entries)
    return sum(result[0] for result in results), sum(result[1] for result in results), changed


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Probe accepted model parameters")
    parser.add_argument("providers", nargs="*", help="Provider ids; defaults to every active provider")
    parser.add_argument("--parameter", choices=sorted({parameter for probes in PROBES.values() for parameter in probes}))
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
    if arguments.replace and (arguments.parameter is not None or arguments.limit is not None):
        parser.error("--replace requires a complete, unfiltered run")
    return arguments


def main() -> int:
    arguments = parse_args()
    load_dotenv(ENV_FILE)
    try:
        catalog_jobs, missing_credentials = _catalog_jobs(set(arguments.providers), arguments.limit)
        planned = _planned_requests(catalog_jobs, arguments.parameter)
        print(f"planned parameter requests: {planned}")
        for missing in missing_credentials:
            print(f"  missing {missing}")
        if arguments.dry_run:
            if missing_credentials and not arguments.allow_missing_credentials:
                return 2
            return 0 if planned or arguments.allow_empty else 1
        attempted, conclusive, changed = asyncio.run(
            run(
                set(arguments.providers),
                arguments.parameter,
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
    print(f"{attempted} parameter probes attempted; {conclusive} conclusive; {changed} catalogs changed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
