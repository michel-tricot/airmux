"""Probe model reachability on every configured provider surface."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import ssl
import sys
import urllib.error
import urllib.request
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

import yaml
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent))

from canonical import write_catalog
from catalog_io import atomic_write_text
from evidence import REACHABILITY_DEFINITIVE, REACHABILITY_PROBE_VERSION, target_fingerprint
from paths import ENV_FILE, TAXONOMY
from provider_profile import endpoints, inference_headers, inference_url, provider_id, select_provider_ids

CTX = ssl.create_default_context()
PROMPT = "say ok"
MAX_TOKENS = 16
CONCURRENCY = 4
TIMEOUT = 60
MAX_ATTEMPTS = 3


@dataclass(frozen=True)
class SmokeResult:
    provider: str
    model_id: str
    endpoint: str
    outcome: str
    detail: str


def classify(status: int, body: str) -> str:
    lowered = body.casefold()
    if status in (401, 403):
        return "access" if "model" in lowered or "access" in lowered else "auth"
    if status == 404:
        return "not_found"
    if status == 429:
        return "rate_limit"
    if status == 400:
        if "does not exist" in lowered or "not found" in lowered or "unknown model" in lowered:
            return "not_found"
        return "bad_request"
    return f"http_{status}"


def request_body(endpoint: str, upstream: str) -> dict:
    if endpoint == "responses":
        return {"model": upstream, "input": PROMPT, "max_output_tokens": MAX_TOKENS, "store": False}
    body = {"model": upstream, "messages": [{"role": "user", "content": PROMPT}]}
    return {**body, "max_tokens" if endpoint == "messages" else "max_completion_tokens": MAX_TOKENS}


def _response_text(endpoint: str, payload: dict) -> str:
    if endpoint == "messages":
        return "".join(block.get("text", "") for block in payload.get("content") or [] if isinstance(block, dict))
    if endpoint == "responses":
        return "".join(
            block.get("text", "")
            for item in payload.get("output") or []
            if isinstance(item, dict)
            for block in item.get("content") or []
            if isinstance(block, dict)
        )
    choices = payload.get("choices") or []
    message = choices[0].get("message") or {} if choices and isinstance(choices[0], dict) else {}
    return message.get("content") or ""


def request(provider: dict, endpoint: str, upstream: str, key: str) -> tuple[str, str]:
    headers = {"Content-Type": "application/json", "User-Agent": "airllm-smoke/1.0", "Accept": "application/json"}
    headers.update(inference_headers(provider, endpoint, key))
    request = urllib.request.Request(
        inference_url(provider, endpoint),
        data=json.dumps(request_body(endpoint, upstream)).encode(),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT, context=CTX) as response:
            payload = json.loads(response.read().decode())
        return "ok", _response_text(endpoint, payload).strip()[:24]
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")[:200]
        return classify(exc.code, detail), " ".join(detail.split())[:90]
    except TimeoutError:
        return "timeout", ""
    except OSError as exc:
        return "transport_error", type(exc).__name__
    except json.JSONDecodeError:
        return "invalid_response", "response was not JSON"


async def run(plans: list[tuple[dict, str, str, str, str]]) -> list[SmokeResult]:
    semaphores: dict[str, asyncio.Semaphore] = {}

    async def one(provider: dict, model_id: str, endpoint: str, upstream: str, key: str) -> SmokeResult:
        semaphore = semaphores.setdefault(provider_id(provider), asyncio.Semaphore(CONCURRENCY))
        async with semaphore:
            for attempt in range(MAX_ATTEMPTS):
                outcome, detail = await asyncio.to_thread(request, provider, endpoint, upstream, key)
                retryable = outcome in {"rate_limit", "timeout", "transport_error", "invalid_response"} or outcome.startswith("http_5")
                if not retryable or attempt == MAX_ATTEMPTS - 1:
                    break
                await asyncio.sleep(2**attempt)
        print({"ok": ".", "not_found": "N", "rate_limit": "~"}.get(outcome, "x"), end="", flush=True)
        return SmokeResult(provider_id(provider), model_id, endpoint, outcome, detail)

    return list(await asyncio.gather(*(one(*plan) for plan in plans)))


def write_back(results: list[SmokeResult], providers: dict[str, dict]) -> int:
    stamp = datetime.now(UTC).strftime("%Y-%m-%d")
    verdicts = {(result.provider, result.model_id, result.endpoint): result.outcome for result in results}
    changed = 0
    for path in sorted((TAXONOMY / "models").glob("*.json")):
        catalog = json.loads(path.read_text())
        provider = providers.get(catalog["provider"])
        if provider is None:
            continue
        for model in catalog["models"]:
            endpoint_status = dict(model.get("endpoint_status") or {})
            for endpoint in endpoints(provider):
                outcome = verdicts.get((provider_id(provider), model["id"], endpoint))
                if outcome is not None:
                    endpoint_status[endpoint] = {
                        "version": REACHABILITY_PROBE_VERSION,
                        "target": target_fingerprint(provider, model, endpoint, "reachability", REACHABILITY_PROBE_VERSION),
                        "outcome": outcome,
                        "checked": stamp,
                    }
            if endpoint_status:
                model["endpoint_status"] = endpoint_status
            current = [
                endpoint_status.get(endpoint)
                for endpoint in endpoints(provider)
                if endpoint_status.get(endpoint, {}).get("version") == REACHABILITY_PROBE_VERSION
                and endpoint_status.get(endpoint, {}).get("target")
                == target_fingerprint(provider, model, endpoint, "reachability", REACHABILITY_PROBE_VERSION)
            ]
            outcomes = [status["outcome"] for status in current if status]
            reachable = (
                True
                if "ok" in outcomes
                else False
                if len(outcomes) == len(endpoints(provider)) and all(outcome in REACHABILITY_DEFINITIVE for outcome in outcomes)
                else None
            )
            if reachable is not None and model.get("reachable") != reachable:
                model["reachable"] = reachable
                model["reachable_checked"] = stamp
        changed += write_catalog(path, catalog)
    return changed


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Probe model reachability")
    parser.add_argument("providers", nargs="*", help="Provider ids; defaults to every active provider")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--yes", action="store_true")
    parser.add_argument("--max-requests", type=int, default=500)
    parser.add_argument("--allow-empty", action="store_true")
    parser.add_argument("--allow-missing-credentials", action="store_true")
    parser.add_argument("--fail-on-unreachable", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    arguments = parser.parse_args(argv)
    if arguments.limit is not None and arguments.limit < 1:
        parser.error("--limit must be positive")
    if arguments.max_requests < 1:
        parser.error("--max-requests must be positive")
    return arguments


def _plans(wanted: set[str], limit: int | None) -> tuple[list[tuple[dict, str, str, str, str]], list[str], dict[str, dict]]:
    providers = {provider["id"]: provider for provider in yaml.safe_load((TAXONOMY / "providers.yml").read_text())["providers"]}
    selected = select_provider_ids(wanted, set(providers))
    plans = []
    missing_credentials = []
    for selected_provider in sorted(selected):
        provider = providers[selected_provider]
        key = os.environ.get(provider["env_var"])
        if not key:
            missing_credentials.append(f"{selected_provider}: no {provider['env_var']}")
            continue
        path = TAXONOMY / "models" / f"{selected_provider}.json"
        if not path.exists():
            continue
        models = json.loads(path.read_text())["models"][:limit]
        plans.extend(
            (provider, model["id"], endpoint, model.get("upstream_id") or model["id"], key) for model in models for endpoint in endpoints(provider)
        )
    return plans, missing_credentials, providers


def main() -> int:
    arguments = parse_args()
    load_dotenv(ENV_FILE)
    try:
        plans, missing_credentials, providers = _plans(set(arguments.providers), arguments.limit)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    maximum_requests = len(plans) * MAX_ATTEMPTS
    print(f"planned reachability requests: {len(plans)}; maximum with transient retries: {maximum_requests}")
    for missing in missing_credentials:
        print(f"  missing {missing}")
    if missing_credentials and not arguments.allow_missing_credentials:
        return 2
    if not plans and not arguments.allow_empty:
        return 2
    if maximum_requests > arguments.max_requests and not arguments.yes:
        print(
            f"the run can schedule {maximum_requests} requests; pass --yes or lower the scope below --max-requests={arguments.max_requests}",
            file=sys.stderr,
        )
        return 2
    if arguments.dry_run:
        return 0
    results = asyncio.run(run(plans))
    print()
    outcomes = Counter(result.outcome for result in results)
    print("outcomes:", dict(outcomes.most_common()))
    for selected_provider in sorted({result.provider for result in results}):
        provider_results = [result for result in results if result.provider == selected_provider]
        ok = sum(result.outcome == "ok" for result in provider_results)
        print(f"  {selected_provider:<11} {ok:>3}/{len(provider_results):<3} ok")
    changed = write_back(results, providers)
    atomic_write_text(
        TAXONOMY / "reports" / "smoke.json",
        json.dumps([asdict(result) for result in sorted(results, key=lambda item: (item.provider, item.model_id, item.endpoint))], indent=2) + "\n",
    )
    failures = [result for result in results if result.outcome != "ok"]
    print(f"{changed} catalogs changed; {len(failures)} requests did not answer")
    return 1 if failures and arguments.fail_on_unreachable else 0


if __name__ == "__main__":
    raise SystemExit(main())
