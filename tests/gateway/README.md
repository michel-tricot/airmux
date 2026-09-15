# Standalone gateway integration tests

Real gateway processes, public HTTP requests, scripted upstream providers, and contract-validated usage events.
No control plane, Postgres, Docker, external provider API, or gateway implementation imports are needed.

## Progression

| Level | File | Coverage |
| --- | --- | --- |
| 1 | `test_01_basic.py` | Readiness, simple inference, authentication, unknown models, malformed input |
| 2 | `test_02_protocols.py` | Every ingress × egress × buffered/streaming pair, UTF-8 fragmentation, usage and cost |
| 3 | `test_03_features.py` | Tools, fragmented arguments, tool results, reasoning, conversations, system prompts, images, PDFs, structured output, aliases |
| 4 | `test_04_policies.py` | Token boundaries, allowlists, denial, prices, parameter adjustment and strict rejection |
| 5 | `test_05_advanced_policies.py` | Selected keys, overlapping policies, model/stream conditions, intersecting allowlists |
| 6 | `test_06_failures.py` | Provider errors, malformed responses, truncated streams, fallback restrictions, attempt limits, deadlines |
| 7 | `test_07_runtime.py` | Client disconnects, estimated usage, restart persistence, concurrent workers, key/policy reloads, invalid files and recovery |

`test_gateway.py` retains the installed CLI setup, validation, taxonomy reload, and restart smoke scenario.
Levels describe increasing complexity, not dependencies. Every test owns its deployment and can run alone.
PR CI runs levels in order, parallelizes variations within each level, and stops advancing when a level fails.

## Run

```bash
uv sync --all-packages --frozen
uv run pytest tests/gateway -n auto
uv run pytest tests/gateway/test_04_policies.py -n auto
uv run pytest tests/gateway -k 'fallback and stream' -n auto
```

By default, the harness uses the `tokkeeper` beside the test Python interpreter.
Set `TOKKEEPER_GATEWAY_BIN` to test an independently installed wheel.
Set `TOKKEEPER_GATEWAY_ARTIFACTS` to collect sanitized diagnostics in a directory outside the checkout:

```bash
TOKKEEPER_GATEWAY_ARTIFACTS=/tmp/gateway-artifacts \
  uv run pytest tests/gateway -n auto --junitxml=/tmp/gateway-results.xml
```

## Add a scenario

Use the `gateway` fixture from `conftest.py`; shared helpers live in `gateway_harness.py`. Add providers, configure
their `Reply` values, add policies, then start.
Assert the caller result, received upstream requests, and expected usage events. Rejected requests must not spend a
provider credential. `gateway.events(count)` validates the full event contract, event/request UUID versions, local
ownership, unique event IDs, cost totals, and absence of inference tokens or provider secrets.

Parameterize applicable protocol variations from `DIALECTS` and `FAMILIES`. `protocols.json` supplies the public routes;
the adapter discovery tests fail if a registered adapter lacks a protocol fixture. A new family also needs independently
authored response and stream fixtures in `upstream.py`. Never generate expectations with the production adapters.
Unsupported combinations get an explicit rejection assertion rather than a skip.

Use events to hold upstream streams and bounded polling to observe reloads. Avoid fixed sleeps, internal function-call
assertions, and complete-response snapshots containing minted IDs or timestamps.

## Event collection

The harness configures `events: {kind: file, path: usage/events.jsonl}`. The sink appends complete JSON Lines, flushes
each event, creates new files privately, and locks writes across threads and processes on a local POSIX filesystem.
It is an inspectable local log, with no export, deduplication, rotation, or `fsync` guarantee.

Events describe metered routes: authentication and parsing failures produce no event, policy denial produces a denied
event, and each fallback attempt produces its own event sharing one request ID. A fallback deadline cancels the active
attempt, which currently records `cancelled`; client disconnects record partial estimated usage where counts are absent.
Control-plane ingestion, durable export replay, and organization/workspace isolation remain in `tests/acceptance`.
