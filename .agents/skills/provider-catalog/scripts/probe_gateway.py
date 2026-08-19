"""Run capability probes through a live data plane."""

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

from capability_support import PROBES
from paths import ENV_FILE, TAXONOMY
from probe_capabilities import classify_response, image_challenge, request_body
from probe_runtime import ProbeOutcome, ProbeReportEntry, http_outcome, write_probe_report

CTX = ssl.create_default_context()
TIMEOUT = 90
CONCURRENCY = 4


def probe(base_url: str, api_key: str, model_id: str, probe_name: str) -> ProbeOutcome:
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Accept": "text/event-stream" if probe_name == "streaming" else "application/json",
        "User-Agent": "airllm-gateway-probe/1.0",
    }
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}/inf/v1/chat/completions",
        data=json.dumps(request_body("chat/completions", model_id, probe_name)).encode(),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT, context=CTX) as response:
            body = response.read().decode(errors="replace")
            expected = image_challenge(model_id)[2] if probe_name == "image_input" else None
            support = classify_response(probe_name, response.status, response.headers.get("Content-Type", ""), body, expected)
            return http_outcome(response.status, support, " ".join(body.split())[:200])
    except urllib.error.HTTPError as exc:
        body = exc.read().decode(errors="replace")
        expected = image_challenge(model_id)[2] if probe_name == "image_input" else None
        support = classify_response(probe_name, exc.code, exc.headers.get("Content-Type", ""), body, expected)
        return http_outcome(exc.code, support, " ".join(body.split())[:200])
    except TimeoutError:
        return ProbeOutcome(None, "timeout")
    except OSError as exc:
        return ProbeOutcome(None, "transport_error", type(exc).__name__)


async def run(base_url: str, api_key: str, models: list[dict], selected: list[str]) -> list[ProbeReportEntry]:
    semaphore = asyncio.Semaphore(CONCURRENCY)

    async def one(model: dict, probe_name: str) -> ProbeReportEntry:
        async with semaphore:
            outcome = await asyncio.to_thread(probe, base_url, api_key, model["model_id"], probe_name)
        print({"supported": ".", "unsupported": "-", None: "?"}[outcome.support], end="", flush=True)
        return ProbeReportEntry(
            model["provider_id"], model["model_id"], "chat/completions", probe_name, outcome.support, outcome.reason, outcome.detail
        )

    return list(await asyncio.gather(*(one(model, probe_name) for model in models for probe_name in selected)))


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Probe capabilities through a live data plane")
    parser.add_argument("--base-url", default=os.environ.get("AIRLLM_GATEWAY_URL", "http://127.0.0.1:8080"))
    parser.add_argument("--api-key", default=os.environ.get("AIRLLM_GATEWAY_API_KEY"))
    parser.add_argument("--provider")
    parser.add_argument("--probe", choices=sorted(PROBES))
    parser.add_argument("--limit", type=int)
    parser.add_argument("--yes", action="store_true")
    parser.add_argument("--max-requests", type=int, default=500)
    parser.add_argument("--dry-run", action="store_true")
    arguments = parser.parse_args(argv)
    if arguments.limit is not None and arguments.limit < 1:
        parser.error("--limit must be positive")
    if arguments.max_requests < 1:
        parser.error("--max-requests must be positive")
    return arguments


def main() -> int:
    load_dotenv(ENV_FILE)
    arguments = parse_args()
    if not arguments.api_key:
        print("no gateway API key; set AIRLLM_GATEWAY_API_KEY or pass --api-key", file=sys.stderr)
        return 2
    taxonomy = yaml.safe_load((TAXONOMY / "taxonomy.yml").read_text())
    models = [model for model in taxonomy["models"] if arguments.provider is None or model["provider_id"] == arguments.provider]
    models = models[: arguments.limit]
    selected = sorted(probe_name for probe_name in PROBES if arguments.probe is None or probe_name == arguments.probe)
    planned = len(models) * len(selected)
    print(f"planned gateway requests: {planned}")
    if planned == 0:
        return 2
    if planned > arguments.max_requests and not arguments.yes:
        print(f"the run schedules {planned} requests; pass --yes or lower --max-requests", file=sys.stderr)
        return 2
    if arguments.dry_run:
        return 0
    report = asyncio.run(run(arguments.base_url, arguments.api_key, models, selected))
    print()
    write_probe_report(TAXONOMY / "reports" / "gateway-probes.json", report)
    conclusive = sum(entry.support is not None for entry in report)
    print(f"{len(report)} gateway probes attempted; {conclusive} conclusive")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
