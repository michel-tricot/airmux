# CPU leads after the aiohttp migration

The current gateway has several measurable CPU opportunities. Start with money-validator ordering because it is a small change with strong boundary evidence. Batching log writes offers more savings but changes log visibility and crash-loss bounds. A native Prometheus recording path is another option if its maintenance cost is justified.

These are diagnostic prototypes, not shipped runtime changes. All comparisons use commit `9d6f10ba` as the baseline, one worker, the same offline Linux ARM64 Docker environment, and the existing Anthropic mock and load drivers. No control-plane server or database runs in the benchmark. The [data and reproduction sources](aiohttp-cpu-leads.json) preserve every trial, direct control, profile, and verification result.

## Buffered-request leads

Three alternating rounds, 20,000 measured requests per variant at concurrency 64, 1,000 warmups, and the 20 ms mock. CPU is gateway process user plus system time divided by requests, including all gateway threads. Disabling observability is used only to locate costs; the candidates in this table retain usage records and metric measurements in the tested configuration.

| Candidate | CPU/request | Savings versus fresh baseline | Savings range across paired rounds | Assessment |
| --- | ---: | ---: | --- | --- |
| Current gateway | 310.0 µs | | | Baseline |
| Move money constraints into Pydantic Core | 299.0 µs | 3.5% | 11.0–13.0 µs | Smallest change, first choice |
| Batch structured log writes | 281.0 µs | 9.4% | 25.0–30.5 µs | Largest independent measured saving |
| Native Prometheus recording | 285.5 µs | 7.9% | 22.5–26.0 µs | More implementation and compatibility work |
| Combined prototype | 271.0 µs | 12.6% | 34.5–43.5 µs | Savings are not additive |

The combined prototype also includes a Pydantic Core log encoder. That encoder alone saved only 1.5 µs in the screening run, which is insufficient evidence to prioritize it. The fresh baseline differs from the earlier transport benchmark; compare paired runs within this investigation rather than mixing numbers across reports. Three laptop rounds establish promising leads, not confidence intervals or production capacity.

### Money validation

`UsdRate` and `UsdAmount` currently place `Field(ge=..., max_digits=..., decimal_places=...)` after custom before/after validators. Inspection of `TypeAdapter.core_schema` confirms that Pydantic implements these constraints as three extra Python callbacks. In the CPU profile, the three money fields of each usage event trigger nine decimal digit extractions in addition to the custom precision checks.

Moving `Field(...)` before the custom validators attaches the constraints to Pydantic Core's decimal schema. The strict string/Decimal input rule, finite-value check, exact precision check, Decimal arithmetic, and fixed-point serializer remain present. This does not use `model_construct`, floats, cached prices, or skipped event validation.

The prototype passed all 128 contract tests. A deterministic differential probe checked 68,946 cases across both money types and three Decimal precision contexts, including invalid inputs, large values, extreme exponents, signed zero, and trailing zeros. Acceptance, successful values, serialization, and JSON schemas matched. Isolated validation took about 40% less CPU on the host; the table measures the smaller effect on complete gateway requests. Exact validation-error text and broader management API behavior still need checking before shipping.

### Logging

The unmodified gateway emits and flushes one structured usage line per request. Stage timing attributed about 32.7 µs/request to the logging call, including 8.9 µs for formatting. A separate format-without-output diagnostic saved 20.5 µs/request, identifying real write/flush cost rather than just JSON encoding.

The batch prototype retains every record and emits at most 100 lines per write, flushing after 100 ms, on an error, and during graceful shutdown. All expected usage records were recovered, and their decoded fields matched baseline records apart from timestamps, request IDs, and measured latency. This adds up to 100 ms of visibility delay and can lose buffered log lines on abrupt process death. It must not be confused with durable usage-event storage, and a production implementation needs bounded buffering, error-path coverage, shutdown coverage, and a clear crash-loss policy.

### Metrics

A successful buffered request records eight measurements: two inflight changes, two HTTP measurements, two upstream measurements, one credential-cache result, and one metering-admission result. Stage timing attributed about 26.3 µs/request to these calls. Turning recording off saved 31 µs/request in the screening run, an upper bound rather than a recommendation.

The native Prometheus prototype uses the already-installed `prometheus_client`, caches labeled children, and retains the existing histogram bucket boundaries. Across all three rounds, the complete set of 102 exported series matched the baseline, including labels, counter values, gauge values, histogram counts, and bucket counts; timing sums and timestamps were allowed to differ. It still needs coverage for other routes, errors, threading, and multiprocess collection. The prototype does not implement OTLP; a production change must preserve that supported export path.

Disabling exemplar sampling through the [supported OpenTelemetry filter](https://opentelemetry-python.readthedocs.io/en/latest/sdk/metrics.html#opentelemetry.sdk.metrics.AlwaysOffExemplarFilter) looked useful in one screening run but failed to show consistent savings in three subsequent CPU-saturation rounds. Do not prioritize that setting from the current evidence. It also removes trace-linked exemplar data where those data are exported.

## CPU versus waiting

With the 20 ms mock, baseline CPU was about 60% of one core. Provider waiting and request scheduling therefore limit how much a CPU improvement increases throughput at fixed concurrency: the combined prototype rose from 1,933 to 2,066 requests/s, about 6.9%.

With the mock delay configured to zero, the current gateway used about 96% of one core. The combined prototype reduced CPU/request from 270.0 to 237.5 µs and raised throughput from 3,579 to 4,033 requests/s, about 12.7%. Both remained near 96% CPU because the closed-loop client used the newly available capacity. This confirms a CPU-capacity improvement; it is not merely work moved to another gateway thread. At a fixed request rate, lower CPU/request should instead reduce CPU utilization.

The synchronous stage timer measured thread CPU, excluding network waiting. Cost calculation itself took only about 2.4 µs/request, so replacing exact Decimal arithmetic is a poor priority. Credential backend loads were zero during the 10,000-request timed phase probe. Repeated route labeling took about 3 µs/request. None of these measurements supports replacing aiohttp again or adding provider pools for this single-provider workload.

## Streaming lead with a demonstrated correctness problem

A separate prototype combines up to 32 already-available SSE frames into one downstream write and flushes at the end of each upstream read. It does not wait for future tokens. Three alternating burst-stream trials produced:

| Workload | Baseline CPU/response | Batched CPU/response | Baseline completion p50 | Batched completion p50 |
| --- | ---: | ---: | ---: | ---: |
| 256 KiB / 4,096 fragments | 36 ms | 30 ms | 52.3 ms | 36.2 ms |
| 8 MiB / 8,192 fragments | 89 ms | 83 ms | 134.1 ms | 105.6 ms |

Complete text, final events, and usage counts matched across 144 responses, including warmups. First-content medians stayed around 4.5–5.3 ms, but the large-stream median increased from 4.51 to 5.16 ms. These burst fixtures do not establish a benefit for ordinary token-paced streams.

**Do not ship this prototype.** A real-gateway failure probe put valid text and a malformed event in the same provider read. Baseline delivered the 64-character valid prefix before reporting the error in all five trials; batching dropped the prefix in all five trials. Folding ahead also changes the state available for cancellation accounting. A production design must preserve valid-prefix delivery, partial usage, and cancellation cleanup before taking these savings.

## Evidence and next steps

The investigation includes a thread-CPU profile of 5,000 requests, a separate synchronous-stage probe of 10,000 requests, eight screening variants, three repeated candidate rounds, three CPU-saturation rounds, burst-stream comparisons, and the malformed-event probe. Profiling and stage timers add overhead; use the uninstrumented comparisons for savings. The official Rust driver measures response headers, with complete-body and token checks before and after buffered trials. Full streaming responses are consumed and verified.

The image is `sha256:949b35ffa05699e3e7d0e7f45b9d47c339a379ed99e263da8cf4056cd1387995`, with four allocated CPUs, 8 GiB, and loopback-only networking. Contract sources in the image were byte-compared with the checkout. Source hashes and runnable diagnostic sources are embedded in the JSON; full logs, profiles, and the money differential corpus remain in `/private/tmp/airmux-aiohttp-cpu-leads`.

Implement and verify the money-validator reorder first. Evaluate log batching if delayed visibility and bounded crash loss are acceptable. Treat the Prometheus path as a separate design decision that must retain OTLP. Keep SSE batching behind a behavior audit covering malformed events and disconnects. Runtime code remains unchanged by this investigation.
