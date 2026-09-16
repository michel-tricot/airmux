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
| 8 | `test_08_metering.py` | Input/output and cache prices, free models/caches, fractional and tiny costs, token counts, fallback costs, partial usage, pricing reloads |

Level 2 also runs `test_openai_sdk.py` with the unmodified SDK and automatic dialect detection.
Level 7 includes `test_gateway.py` for installed CLI setup, validation, taxonomy reload and restart, plus
`test_local_mode.py` for embedded taxonomy with a minimal environment and no control plane.
Levels describe increasing complexity, not dependencies. Every test owns its deployment and can run alone.
PR CI runs levels in order, parallelizes variations within each level, and stops advancing when a level fails.

## Run

```bash
uv sync --all-packages --frozen
uv run pytest tests/acceptance/gateway -n auto
uv run pytest tests/acceptance/gateway/test_04_policies.py -n auto
uv run pytest tests/acceptance/gateway/test_08_metering.py -n auto
uv run pytest tests/acceptance/gateway -k 'fallback and stream' -n auto
```

By default, the harness uses the `airmux` beside the test Python interpreter.
Set `AIRMUX_GATEWAY_BIN` to test an independently installed wheel.
Set `AIRMUX_GATEWAY_ARTIFACTS` to collect sanitized diagnostics in a directory outside the checkout:

```bash
AIRMUX_GATEWAY_ARTIFACTS=/tmp/gateway-artifacts \
  uv run pytest tests/acceptance/gateway -n auto --junitxml=/tmp/gateway-results.xml
```

## Add a scenario

Use the `gateway` fixture from `conftest.py`; shared helpers live in `gateway_harness.py`. Add providers, configure
their `Reply` values, add policies, then start.
Assert the caller result, received upstream requests, and expected usage events. Rejected requests must not spend a
provider credential. `gateway.events(count)` validates the full event contract, event/request UUID versions, local
ownership, unique event IDs, cost totals, and absence of inference tokens or provider secrets.
Check designated wire fields, complete message sequences, attachment types and media data, and tool-call/result
relationships. A value appearing somewhere in serialized JSON does not prove that a provider can use it.

Parameterize applicable protocol variations from `DIALECTS` and `FAMILIES`. `protocols.json` supplies the public routes;
the adapter discovery tests fail if a registered adapter lacks a protocol fixture. A new family also needs independently
authored response and stream fixtures in `upstream.py`. Never generate expectations with the production adapters.
Unsupported combinations get an explicit rejection assertion rather than a skip.

Feature inputs and provider expectations are handwritten beside each scenario in `test_03_features.py`. Attachment
tables contain only the differing native parts; filenames and schema naming metadata are direct expected values.
Surrounding messages are constructed once for the caller and once independently for the provider expectation.
Scenarios compare complete designated fields. Native response readers remain explicit; the tool-history reader requires
string arguments in OpenAI wire formats and compares their decoded JSON, preserving all other fields exactly.
Protocol cases declare expected auth headers, usage, costs, and stream terminal lines/events. Policy cases declare input
and output token-limit field names; adjustment metadata is checked in every caller dialect.

Use events to hold upstream streams and bounded polling to observe reloads. Avoid fixed sleeps, internal function-call
assertions, and complete-response snapshots containing minted IDs or timestamps.
Invalid reloads have no public acknowledgement: the recovery scenario checks successful inference, readiness, and the
original event bundle identity throughout ten configured reload intervals before publishing a valid replacement.

Metering expectations are explicit dollar amounts calculated independently of the gateway. Cost comparisons use
`rel=1e-12, abs=1e-15`: pytest's default absolute tolerance would let sub-microdollar charges disappear. The provider
fixture accepts native usage JSON in `Reply(usage=...)`; omit the argument for its default counts, or use `None` for
absent usage. Cache-write counts are exercised where the provider protocol reports them. Fixed estimation fixtures use
the unknown upstream model's `o200k_base` encoding: `user: hi` is three tokens and `one two` is two.
Partial usage retains reported cache-only prompts on disconnect; it estimates only counts the provider has not supplied.
Explicit all-zero OpenAI Chat Completions and Anthropic usage currently renders zero counts marked as estimated;
the event meter fills those counts from the request/response text. OpenAI Responses treats an explicit zero usage
object as authoritative, so its zero counts remain free. The all-zero cases document both caller usage and event cost.
OpenAI disconnect tables retain one case because usage arrives after the held content frame; Anthropic retains three
because its initial frame reports input and cache counts before cancellation.
Metering case tables pair handwritten native usage JSON with independently written token counts and dollar amounts.
The scenario functions select a case for each family without translating usage or calculating expectations. Disconnect
cases reuse native payloads but declare their partial expectations separately. Every scenario remains parameterized over
the full applicable protocol matrix; a missing family or case fails instead of falling back to shared defaults.

## Performance and regression tracking

The `gateway-performance` CI job compares independently built base and candidate wheels on the same runner.
For a PR, the base is its target commit and the candidate is the merge commit tested by CI. A push to `main` compares
with the preceding commit; a manual run compares with `main`. Both gateways run the candidate checkout's benchmark,
so changes to the workload apply equally to both versions.

`performance.py` measures buffered latency, streaming time to the first non-empty text delta, throughput at concurrency
1, 8 and 32, and latency with 100 applicable policies. Direct upstream calls at concurrency 1 and 32 reveal changes in
the load generator or stub. These are representative OpenAI Chat Completions workloads; the correctness suite covers
the full protocol matrix. Longer prompts, sustained token streams, worker scaling and real providers need separate
workloads before drawing conclusions about those paths.

Each workload warms persistent connections before a two-second closed-loop load window. Five rounds alternate
base/candidate execution order. The report compares the median of each round's p50/p95/p99 latency, streaming first
content latency and completed requests per second. Request failures, incorrect text, incomplete streams and lost usage
events fail the job. Both versions use one gateway worker and the existing durable SQLite event queue; event writes
are included, periodic export is excluded, and bundle polling runs every five seconds. The lightweight provider runs
in its own async process, reuses the handwritten native response fixtures, supports persistent connections and captures
no request history during load.

Performance changes start as warnings, not PR gates. A warning requires more than 20% slower latency or lower
throughput, plus more than 1ms absolute change for latency. These initial thresholds are investigation triggers, not
statistical significance tests. Inspect direct-upstream changes and individual rounds, and rerun a suspicious result.
Once runner noise and normal variation are known, we can choose blocking thresholds for specific workloads.

Every run shows its comparison in the Actions summary and uploads `measurements.json` and `summary.md` as the
`gateway-performance` artifact for 90 days. JSON contains raw per-request timings, both commit identities, runner
metadata, workload settings and comparisons. Main-branch runs provide a bounded history; compare PR/base ratios
before comparing absolute numbers from different machines. This does not create a permanent metrics store or chart.

To compare any two installed gateways locally, choose a fresh output directory:

```bash
uv run python tests/acceptance/gateway/performance.py \
  --base-bin /path/to/base/bin/airmux \
  --candidate-bin /path/to/candidate/bin/airmux \
  --base-revision BASE_SHA --candidate-revision CANDIDATE_SHA \
  --output "$(mktemp -d)"
```

Use `--rounds 3 --duration-s 0.1 --warmup 1` for a harness smoke check. Short runs are not useful regression evidence.
Run benchmarks alone, without pytest parallelization or other local load. Full-stack scenarios protect durable export
correctness; remote polling/export performance and worker scaling need separate benchmark workloads.

## CI failure display

The installation job's Actions summary shows installation checks, reporting checks, counts by level and expandable assertion/setup-error tracebacks
with the complete parameterized test name. Its `always()` reporting step runs after a failing test level; later levels
remain stopped. Up to ten failures also produce error annotations. Full pytest tracebacks stay in the original step
logs, and the `gateway-integration` artifact retains XML plus sanitized caller, gateway and upstream diagnostics.
Summary details are bounded to the first 50 failures and 10,000 escaped characters per failure.

`ci_report.py` reads pytest's JUnit output without changing pytest's exit status or test behavior. To preview it locally:

```bash
uv run python tests/acceptance/gateway/ci_report.py /tmp/gateway-results --summary /tmp/gateway-summary.md
```

## Event collection

The harness configures `events: {kind: file, path: usage/events.jsonl}`. The sink appends complete JSON Lines, flushes
each event, creates new files privately, and locks writes across threads and processes on a local POSIX filesystem.
It is an inspectable local log, with no export, deduplication, rotation, or `fsync` guarantee.

Events describe metered routes: authentication and parsing failures produce no event, policy denial produces a denied
event, and each fallback attempt produces its own event sharing one request ID. A fallback deadline cancels the active
attempt, which currently records `cancelled`; client disconnects record partial estimated usage where counts are absent.
Control-plane ingestion, durable export replay, and organization/workspace isolation remain in `tests/acceptance/full_stack`.
