"""Call every catalogued model once and report what actually answers.

The catalog says a model exists and is serverless. This proves it: one real request per
model, straight at the provider, using the upstream_model the taxonomy would send.

    uv run python smoke.py                 every model
    uv run python smoke.py groq openai     only these providers
    uv run python smoke.py --limit 5       first five per provider, for a cheap pilot

Requests are deliberately tiny: a three-word prompt and a small output cap. The point is
whether the id resolves and the credential works, not whether the answer is good.

Reasoning models bill their hidden reasoning as output, so the cap is 16 rather than 1: a
cap of 1 makes some of them return an empty completion and look like a failure. Even at the
most expensive output rate in the catalog that is well under a cent per call.

Failures are classified rather than counted, because the classes mean different things:

  auth        the credential is wrong or lacks access to that model
  not_found   the id does not resolve, which is a catalog bug
  bad_request the id resolves but rejects this shape, e.g. audio-only models
  access      the account is not entitled to the model, common on preview tiers
  rate_limit  the host is throttling, so rerun rather than trust the result

not_found is the one that means the catalog is wrong. The others describe the account.

## Reachability is written back

A verdict lands on each model as `reachable` and `reachable_checked`, and build_taxonomy
skips anything explicitly unreachable. That is the difference between a catalog that claims
a model is callable and one that has checked.

Only definitive outcomes set a verdict. Throttling, timeouts and 5xx say something about the
moment rather than the model, so they leave the previous verdict alone: a rate limit must
never quietly delete a working model from the applied taxonomy.

A model with no verdict is included. Absence of evidence is not evidence of absence, and
providers whose key is missing are never tested at all.

reachable_checked is the date the verdict last changed, not the date it was last checked, so
a run that confirms the status quo leaves every file untouched. The detailed run log in
reports/ is a local artefact and is not committed: it carries each model's reply, which
differs every run.
"""

from __future__ import annotations

import asyncio
import json
import os
import ssl
import sys
import urllib.error
import urllib.request
from collections import Counter
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from paths import TAXONOMY

CTX = ssl.create_default_context()
PROMPT = "say ok"
MAX_TOKENS = 16
CONCURRENCY = 4          # per provider; hosts throttle per account, not per model
TIMEOUT = 60

# outcomes that say something durable about the model rather than about this moment
DEFINITIVE = {"ok", "not_found", "bad_request", "access", "auth"}


def classify(status: int, body: str) -> str:
    lowered = body.lower()
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


def request(provider: dict, upstream: str, key: str) -> tuple[str, str]:
    base = provider["base_url"].rstrip("/")
    anthropic = provider["id"] == "anthropic"
    url = f"{base}/messages" if anthropic else f"{base}/chat/completions"
    body = {
        "model": upstream,
        "messages": [{"role": "user", "content": PROMPT}],
        "max_tokens" if anthropic else "max_completion_tokens": MAX_TOKENS,
    }
    # Groq and Together sit behind Cloudflare, which rejects urllib's default agent with
    # "error code: 1010" — a bot-detection block that reads exactly like an auth failure
    headers = {"Content-Type": "application/json", "User-Agent": "airllm-smoke/1.0", "Accept": "application/json"}
    if anthropic:
        headers["x-api-key"] = key
        headers["anthropic-version"] = "2023-06-01"
    else:
        headers["Authorization"] = f"Bearer {key}"

    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT, context=CTX) as response:
            payload = json.loads(response.read().decode())
        if anthropic:
            text = "".join(b.get("text", "") for b in payload.get("content") or [])
        else:
            text = ((payload.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
        return "ok", (text or "").strip()[:24]
    except urllib.error.HTTPError as e:
        detail = e.read().decode()[:200]
        return classify(e.code, detail), detail.replace("\n", " ")[:90]
    except TimeoutError:
        return "timeout", ""
    except Exception as e:  # noqa: BLE001 - any transport failure is a result, not a crash
        return "error", type(e).__name__


async def run(models: list[tuple[dict, str, str, str]]) -> list[tuple]:
    semaphores: dict[str, asyncio.Semaphore] = {}
    results = []

    async def one(provider, model_id, upstream, key):
        sem = semaphores.setdefault(provider["id"], asyncio.Semaphore(CONCURRENCY))
        async with sem:
            outcome, detail = await asyncio.to_thread(request, provider, upstream, key)
        results.append((provider["id"], model_id, outcome, detail))
        mark = {"ok": ".", "not_found": "N", "rate_limit": "~"}.get(outcome, "x")
        print(mark, end="", flush=True)

    await asyncio.gather(*(one(*m) for m in models))
    return results


def write_back(results: list[tuple]) -> None:
    """Record the verdict on each model, leaving inconclusive outcomes untouched."""
    from datetime import datetime, timezone

    from canonical import write_catalog

    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    verdicts = {(p, m.split("/", 1)[1]): o for p, m, o, _ in results}
    changed = 0
    for path in sorted((TAXONOMY / "models").glob("*.json")):
        doc = json.loads(path.read_text())
        touched = False
        for model in doc["models"]:
            outcome = verdicts.get((doc["provider"], model["id"]))
            if outcome is None or outcome not in DEFINITIVE:
                continue
            reachable = outcome == "ok"
            # the stamp marks when the verdict last changed, not when it was last checked:
            # a per-run timestamp would rewrite every catalog on every run and drown the diff
            if model.get("reachable") != reachable:
                model["reachable"] = reachable
                model["reachable_checked"] = stamp
                touched = True
        if touched or any("reachable" in m for m in doc["models"]):
            write_catalog(path, doc)
            changed += 1
    print(f"\nverdicts written to {changed} catalogs")


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    limit = next((int(a.split("=")[1]) for a in sys.argv[1:] if a.startswith("--limit=")), None)

    providers = {p["id"]: p for p in yaml.safe_load((TAXONOMY / "providers.yml").read_text())["providers"]}
    spec = yaml.safe_load((TAXONOMY / "taxonomy.yml").read_text())

    plan, skipped = [], []
    seen: Counter = Counter()
    for model in spec["models"]:
        pid = model["provider_id"]
        if args and pid not in args:
            continue
        provider = providers[pid]
        key = os.environ.get(provider["env_var"])
        if not key:
            skipped.append((pid, model["model_id"], f"no {provider['env_var']}"))
            continue
        if limit and seen[pid] >= limit:
            continue
        seen[pid] += 1
        plan.append((provider, model["model_id"], model["upstream_model"], key))

    print(f"calling {len(plan)} models across {len(seen)} providers, {MAX_TOKENS} output tokens each")
    print("  . ok   N id does not resolve   ~ throttled   x other\n  ", end="")
    results = asyncio.run(run(plan))
    print("\n")

    by_outcome = Counter(r[2] for r in results)
    print("outcomes:", dict(by_outcome.most_common()))
    print()
    for pid in sorted(seen):
        rows = [r for r in results if r[0] == pid]
        ok = sum(1 for r in rows if r[2] == "ok")
        print(f"  {pid:<11} {ok:>3}/{len(rows):<3} ok")
    failures = [r for r in results if r[2] != "ok"]
    if failures:
        print(f"\n{len(failures)} did not answer:")
        for pid, mid, outcome, detail in sorted(failures, key=lambda r: (r[2], r[1])):
            print(f"  {outcome:<11} {mid:<44} {detail[:70]}")
    if skipped:
        print(f"\nskipped {len(skipped)} for a missing credential")
    write_back(results)
    (TAXONOMY / "reports").mkdir(exist_ok=True)
    (TAXONOMY / "reports" / "smoke.json").write_text(
        json.dumps([{"provider": p, "model_id": m, "outcome": o, "detail": d} for p, m, o, d in sorted(results)], indent=2) + "\n"
    )
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
