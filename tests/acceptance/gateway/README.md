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

Level 2 also runs `test_openai_sdk.py` with the unmodified SDK against its path-bound protocol.
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
Explicit all-zero OpenAI Chat Completions and Anthropic usage renders zero caller counts; the event meter estimates
those counts from the request and response text. OpenAI Responses treats an explicit zero usage object as authoritative,
so its zero counts remain free. The all-zero cases document both caller usage and event cost.
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

`performance.py` measures HTTP/1.1 buffered latency and throughput with SQLite and dev-null event collection at
concurrency 1, 8 and 32. The dev-null workload also runs at concurrency 128, above the gateway's 100-connection
provider pool, to expose assignment contention. HTTP/2 dev-null workloads run at concurrency 1, 32 and 128, with
concurrency 32 streaming coverage. Direct HTTP/1.1 controls run at concurrency 1, 32 and 128; direct HTTP/2 controls
run at concurrency 1 and 32. Streaming records time to the first non-empty text delta, and the policy workload records
latency with 100 applicable policies. These are representative OpenAI Chat Completions workloads; the correctness
suite covers the full dialect and provider-family matrix. Use `--request-bytes`, `--response-bytes`, `--stream-chunks`,
`--stream-chunk-delay-ms`, `--client-read-delay-ms`, `--upstream-delay-ms`, `--request-timeout-s` and `--scenario` for
focused payload, pacing, backpressure and provider-delay studies without expanding the nightly matrix. The separate scaling experiment below measures worker and pool limits. Real providers need their own workloads.

Each workload warms persistent connections before a two-second closed-loop load window. Five rounds alternate
base/candidate execution order. The report compares the median of each round's p50/p95/p99 latency, streaming first
content latency and completed requests per second. Request failures, incorrect text, incomplete streams and lost usage
events fail the job. Both versions use one gateway worker. SQLite request-path reservation and enqueueing are included,
while its storage thread drains concurrently; paired dev-null workloads isolate that metering persistence cost. Periodic
export and bundle polling are excluded with one-hour intervals. Lightweight HTTP/1.1 and HTTP/2 providers run in
their own async processes, reuse the handwritten native response fixtures, support persistent connections and capture
no request history during load. The HTTP/2 provider uses a per-run trusted certificate and TLS ALPN, and the provider
rejects requests that arrive over a protocol other than the workload's declared protocol. Its one-hour idle timeout
and one-million-request keepalive limit keep a connection stable across every bracketed window. The HTTPX2 load
generator is shared by both revisions, so control-side pool behavior cannot bias the gateway comparison.

Each proxied workload also has its own direct-before and direct-after windows, including streaming and the policy
workload. All three use the same request fields, fixed provider response, concurrency and provider protocol. Only the
model name differs at ingress; direct requests use the translated upstream name. HTTP/1.1 direct controls use one
persistent connection per worker. HTTP/2 direct controls multiplex all workers over one connection, matching the
gateway's shared-client topology. Caller-to-gateway traffic remains HTTP/1.1. Streaming controls request usage just as
the gateway does. The providers retain idle connections for one hour, avoiding server-side expiry races while the
bracketed control windows run. Client keepalive expiry stays at five seconds. The 100 policies apply to the proxy and
leave this request's token limit unchanged.

For round r, the incremental HTTP proxy latency estimate is:

```text
direct_mean_r = (mean(direct_before_r) + mean(direct_after_r)) / 2
overhead_r = mean(proxied_r) - direct_mean_r
reported_overhead = median(overhead_r across rounds)
```

Buffered and policy workloads use completed request latency; streaming also applies the same calculation to time
until the first non-empty content delta. These are differences in window means, not percentiles of paired per-request
overhead. Direct and proxied windows have different request counts under closed-loop load; the two control means
receive equal weight. No p95/p99 values are subtracted. Total proxied latency is still reported separately.

This measures the incremental cost of the extra local HTTP hop, authentication, translation, applicable policy
evaluation, metering, the selected SQLite or dev-null event sink, client parsing, scheduling and connection-pool/queueing effects.
It does not isolate time executing gateway code. Model inference, external providers/network variability,
control-plane traffic, periodic event export and bundle polling, startup and warmup are excluded. Provider waits occur
in both paths. Windows run sequentially, so controls do not compete with proxy traffic; time-varying runner load can
still bias their difference. At higher concurrency, each path's queueing and sustainable throughput can differ.

Reports retain negative/zero estimates, show the range of round estimates and maximum absolute direct-before/after
mean drift in milliseconds, and label latency estimates noisy if any round is non-positive or control drift reaches
either version's median estimate. These diagnostics are not confidence intervals. Relative changes are N/A if either
estimate is non-positive. Positive but noisy estimates can still trigger report-only warnings and need investigation.
Direct and proxied requests per second are shown alongside `throughput_cost_pct = 100 * (1 - proxied_rps / direct_rps)`,
using the mean of control-window RPS per round and then the median across rounds. Its absolute changes are percentage
points. Throughput warnings use proxied RPS, not the derived cost.

Performance changes start as warnings, not PR gates. A warning requires more than 20% slower latency or lower
throughput, plus more than 1ms absolute change for latency. These initial thresholds are investigation triggers, not
statistical significance tests. The 1ms floor misses sub-millisecond overhead regressions even when their percentage
change is large; percentages near zero are unstable, and a non-positive baseline cannot trigger a relative warning. Inspect direct-upstream changes and individual rounds, and rerun a suspicious result.
Once runner noise and normal variation are known, we can choose blocking thresholds for specific workloads.

Every run shows its comparison in the Actions summary and uploads `measurements.json` and `summary.md` as the
`gateway-performance` artifact for 90 days. JSON contains raw per-request timings, both commit identities, runner
metadata, workload/protocol/connection settings, the gateway's explicit provider pool limits and timeouts, all direct
controls, derived round estimates, exact verified metering event counts and comparisons. The methodology is included
in both files, explicitly including durable SQLite event collection. Main-branch runs provide a bounded history; compare PR/base ratios
before comparing absolute numbers from different machines. This does not create a permanent metrics store or chart.

To compare any two installed gateways locally, choose a fresh output directory:

```bash
uv run python tests/acceptance/gateway/performance.py \
  --base-bin /path/to/base/bin/airmux \
  --base-harness /path/to/base/checkout/tests/acceptance/gateway \
  --candidate-bin /path/to/candidate/bin/airmux \
  --base-revision BASE_SHA --candidate-revision CANDIDATE_SHA \
  --output "$(mktemp -d)"
```

Each gateway uses the fixture harness from its own checkout, so contract changes do not prevent the
older gateway from starting. Both revisions run the candidate benchmark's measured workloads.

Use `--rounds 3 --duration-s 0.1 --warmup 1` for a harness smoke check. Short runs are not useful regression evidence.
Use `--upstream-delay-ms 50` to repeat the same experiment with 50ms of deterministic provider wait per request.
`test_provider_wait_is_not_attributed_to_gateway_overhead` compares 0ms/50ms real HTTP runs for buffered, first-content
and policy latency at concurrency 1: direct latency must rise by over 40ms while the overhead estimate changes by less
than 15ms. This generous bound checks wait attribution, not sub-millisecond regression sensitivity. The installation
job runs it against the independently installed candidate wheel. Repeating the benchmark with the flag checks both
installed versions with the same controls and exact metering counts.

Run benchmarks alone, without pytest parallelization or other local load. Full-stack scenarios protect durable export
correctness; remote polling/export performance needs separate benchmark workloads.

## Codec and capacity experiments

Use the installed Pydantic Core implementation to compare request decoding, provider body encoding, and stream-event
parsing against the previous stdlib operations. Encoding includes Pydantic model dumping and provider alias mapping:

```bash
uv run python tests/acceptance/gateway/performance_codecs.py --output /tmp/codecs.json
```

Run the paired benchmark above three times with distinct output directories: once with `--scenario buffered_devnull`,
once with `--scenario buffered_devnull --request-bytes 262144`, and once with
`--scenario stream --response-bytes 8192 --stream-chunks 256`. The streaming fixture emits 256 content events plus
finish, usage, and terminal events. `--request-bytes` sizes the prompt text; JSON framing adds bytes to the HTTP body.
Use the same interpreter, locked dependency versions, and machine for both installed revisions. Inspect absolute
changes in overhead and requests per second alongside codec timings. Microbenchmarks do not establish gateway speedups.

Run the candidate's worker and pool matrix separately:

```bash
uv run python tests/acceptance/gateway/performance_scaling.py \
  --candidate-bin /path/to/candidate/bin/airmux \
  --candidate-revision CANDIDATE_SHA \
  --output /tmp/gateway-scaling
```

Nightly CI runs codecs with the paired benchmark and runs scaling in a separate job, retaining artifacts for 90 days.
The output directory must be new. Three rounds reverse execution order on alternate rounds. Each round covers
workers 1/2/4, total connections 100/256 per worker, concurrency 32/128, and provider HTTP/1.1/HTTP/2, for 24 cases.
Keepalive stays at 20 per worker; timeouts and expiry stay at their defaults. All cases use buffered dev-null collection
with authentication, policy, translation, usage logging, and metrics active. The ordinary base/candidate benchmark
uses each binary's default configuration; the scaling experiment explicitly supplies the new pool settings.

`measurements.json` retains each case's settings, raw direct/proxied timings, process CPU deltas, and connection counts.
`summary.md` reports medians for throughput, p50/p95/p99 latency, direct-controlled overhead, and CPU usage in cores.
CPU uses `/proc` on Linux or `ps` on macOS and covers warmup plus load. Gateway CPU includes its workers and reports
individual PIDs in the raw data; the client count excludes children. Provider connections are distinct inference
client addresses observed during that window, including connection churn, rather than a peak-open-socket count.
Address tracking is enabled only for the scaling experiment and captures no request payloads.

Caller traffic stays HTTP/1.1. HTTP/2 direct controls multiplex over one connection; several gateway workers can each
open a provider connection. Account for this topology when interpreting scaling. If throughput improves with workers
while one worker consumes one core, inspect CPU/event-loop work. If increasing the pool helps at fixed worker count,
inspect connection assignment and queueing. Check provider and load-generator CPU before attributing a plateau to the
gateway. Do not infer a pool bottleneck from configured limits alone. The matrix reports measurements without changing
production defaults or imposing timing gates on CI.

## CI failure display

The gateway CI job installs the wheel rebuilt from the source distribution and runs this entire directory with xdist.
Adding or moving a test in the directory changes no workflow YAML. The job retains its report and diagnostics even
when a test fails.

The Actions summary shows counts and expandable assertion/setup-error tracebacks with the complete parameterized test
name. Its `always()` reporting step runs after a failure. Full pytest tracebacks stay in the original step logs, and
the gateway artifact retains XML plus sanitized caller, gateway and upstream diagnostics.
Summary details are bounded to the first 50 failures and 10,000 escaped characters per failure.

`ci_report.py` reads pytest's JUnit output without changing pytest's exit status or test behavior. To preview it locally:

```bash
uv run python tests/acceptance/gateway/ci_report.py /tmp/gateway-results --summary /tmp/gateway-summary.md
```

## Event collection

The harness configures `events: {kind: file, path: usage/events.jsonl}`. The sink appends complete JSON Lines, creates
new files privately, and appends each batch in one write across threads and processes on a local POSIX filesystem.
It is an inspectable local log, with no export, deduplication, rotation, or `fsync` guarantee.

Events describe metered routes: authentication and parsing failures produce no event, policy denial produces a denied
event, and each fallback attempt produces its own event sharing one request ID. A fallback deadline cancels the active
attempt, which currently records `cancelled`; client disconnects record partial estimated usage where counts are absent.
Control-plane ingestion, durable export replay, and organization/workspace isolation remain in `tests/acceptance/full_stack`.
