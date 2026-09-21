# Airmux throughput audit

Airmux is primarily **CPU-bound in this one-worker benchmark**. Much of that CPU is spent managing asynchronous HTTP I/O: connection-pool scans, socket state checks, Python protocol processing, and client bookkeeping. The requests already await the provider asynchronously. Adding more asynchronous concurrency or retaining more idle connections does not remove that work.

All new probes use the same offline ARM64 Docker image, four-core/8-GiB container limit, one worker, official Rust driver, Anthropic request, and 20 ms mock delay. Both the driver and provider are local to that container. Each unprofiled throughput trial warms up with 1,000 requests, then measures 20,000 at concurrency 64. Gateways start fresh; three comparison rounds alternate variant order and bracket each round with direct controls. Separate profiling probes use 5,000 measured requests. Raw results, diagnostic source, versions, and validation are in [the audit data](gateway-throughput-audit.json).

## What costs throughput

Three-round medians, with no function profiling or counters enabled in these throughput trials:

| Diagnostic | Requests/s | Worker CPU | CPU per request |
| --- | ---: | ---: | ---: |
| Direct mock | 2,544 | Not measured | Not measured |
| Full Airmux, default pool | 1,406 | 91.1% | 632.5 µs |
| Suppress structured logs only | 1,512 | 89.2% | 597.0 µs |
| Suppress metrics only | 1,452 | 90.1% | 618.5 µs |
| Suppress logs and metrics | 1,536 | 88.6% | 579.5 µs |
| Bare Starlette + HTTPX2 proxy | 1,902 | 74.5% | 393.0 µs |
| Full Airmux, 100 idle connections | 993 | 73.2% | 747.0 µs |

CPU is process CPU, where 100% means one occupied core. Logs and metrics together account for about a 9% throughput difference in these controls, not the full drop to the mock. The default baseline ranged from 1,404 to 1,452 requests/s; the direct controls ranged from 2,464 to 2,564. The baseline is slightly higher than the earlier comparison, so each experiment uses its own contemporaneous controls.

The stripped variants are diagnostic controls. Suppressing logging preserves usage-event construction; suppressing metric updates preserves the request's domain behavior. The bare proxy removes authentication, canonical translation, accounting, and middleware but retains Starlette, Uvicorn, and the same HTTPX2 client. These variants are not proposed production configurations. Removing all Airmux features still leaves a substantial gap to the direct mock.

A separate three-round transport-only comparison produced **36% more throughput and 50% less CPU per request**:

| Full Airmux request pipeline | Requests/s | Worker CPU | CPU per request |
| --- | ---: | ---: | ---: |
| Existing HTTPX2 transport | 1,382 | 92.5% | 677.0 µs |
| Buffered aiohttp diagnostic | 1,880 | 62.0% | 335.5 µs |

Direct controls in this series had a median 2,550 requests/s. Every paired round improved: the alternative transport ranged from 1,853 to 1,892 requests/s, while the baseline ranged from 1,362 to 1,410. After the substitution, the worker is no longer near CPU saturation at concurrency 64; remaining latency includes request processing, event-loop scheduling, and the fixed upstream wait. The gain does not imply that all remaining latency is CPU execution.

The alternative transport is a temporary buffered HTTP/1.1 probe using the image's already-installed aiohttp 3.14.1, its C HTTP response parser, and a shared session. It leaves the full successful Airmux request pipeline enabled, including authentication, canonical translation, usage-event construction, logging, and metrics. Complete response text and provider token counts were checked, as were exact usage-log counts. The client keeps up to 100 active connections with five-second keepalive expiry; its idle-pool policy differs from HTTPX2's 20-idle limit. This measures the combined transport implementation and pool behavior, not an isolated parser speedup.

It is not a production transport implementation. Streaming, HTTP/2, cancellation, timeout semantics, decompression, and provider error mapping require implementation and acceptance coverage before adoption. The prototype only replaces the buffered outbound request used by this workload. No runtime or dependency changes were applied to the project.

## CPU execution versus I/O waiting

Each request waits approximately 20 ms at the mock. Up to 64 such waits overlap, so this waiting does not require 64 times 20 ms of CPU. At steady concurrency, throughput is constrained by both response time and available CPU. Airmux's Python worker approaches one core's capacity; added work queues behind other requests and increases latency. A roughly 0.7 ms CPU cost per request can therefore cause much more than 0.7 ms of extra end-to-end latency under load.

A separate instrumented 20,000-request run measured **12.37 seconds of user CPU and 0.75 seconds of kernel CPU** in a 14.30-second window. About 94% of worker CPU was user-space execution. Both this run and the alternative-transport diagnostic recorded **zero container CPU throttling**.

Synchronous thread-CPU timers localized these costs in the full default gateway:

| Work | CPU per request |
| --- | ---: |
| HTTP pool assignment | 115.4 µs |
| Canonical parsing, request/response translation, and rendering | 49.3 µs |
| Routing and reconciliation | 17.1 µs |
| Usage-event construction and cost calculation, excluding its log | 26.6 µs |
| Structured usage log | 34.8 µs |
| Metric updates | 30.9 µs |
| Authentication | 6.0 µs |

These named sections account for approximately 280 of 656 µs per request. The remainder includes HTTP client/protocol processing outside pool assignment, server/middleware execution, credential handling, scheduling, and instrumentation. The table avoids double-counting logging inside usage-event construction. These timers add overhead and are used for attribution, not as replacement throughput numbers. Pool assignment alone consumed 2.31 seconds of thread CPU, approximately 18% of measured worker CPU.

The diagnostic separates worker user/system CPU, synchronous function thread-CPU time, and total container quota counters. Socket waiting remains asynchronous. The timed workload uses loopback HTTP to a numeric IP, so it includes neither external network latency nor DNS/TLS setup. No control-plane server, database access, or durable outbox writes occur in these probes.

The original benchmark's Rust driver times successful response headers without explicitly consuming the body. That behavior is unchanged across every variant. Separate full-body checks catch response corruption, but these results are specific to that driver and are not production capacity claims. Host background load remains uncontrolled; ranges are observations, not confidence intervals.

## The HTTP pool hotspot

HTTPX2/httpcore2 2.13.0 uses one shared client, so constructing a fresh client per request is not the problem. Uvicorn already selects uvloop and httptools in this image.

`httpcore2._async.connection_pool.AsyncConnectionPool._assign_requests_to_connections` runs when a request enters and leaves the pool. It walks connection state and pending requests, rebuilds reusable connections, checks idle expiry, and may create or close sockets. An idle expiry check calls AnyIO's socket-attribute machinery and `select.poll(0)` to detect disconnected sockets.

In the 20,000-request instrumented screen:

- The default pool made 40,000 assignment passes; the pool sizes summed to approximately 2.36 million across those passes, before counting the multiple loops within each pass
- It opened 3,047 upstream TCP connections during the measured window after warmup
- Pool assignment took 2.41 seconds of synchronous elapsed time; the separate diagnostic above measured 2.31 seconds of thread CPU, approximately 18% of its worker CPU
- Retaining 100 idle connections eliminated new TCP connections but increased pool assignment time to 4.31 seconds and reduced throughput

The profiler corroborates the mechanism. The default pool made 105,674 socket-readability checks for 5,000 requests; the larger pool made 243,170. This is approximately 21 versus 49 checks per request. Retaining more idle sockets gives the pool more sockets to inspect. Connection churn exists, but eliminating it by changing this limit alone is not an improvement.

The default-pool cProfile diagnostic attributes approximately 65% of its recorded execution time to the outbound HTTPX2 request subtree, including approximately 24% to connection-pool assignment. Usage-event construction including logging accounts for approximately 7%, while authentication is below 1%. These are hotspot rankings from an instrumented run, not unbiased CPU percentages: profiling slowed the worker significantly. The unprofiled experiments and thread-CPU measurements are the quantitative evidence for improvement priorities.

## Recommended improvements

1. **Prioritize the outbound HTTP transport**: optimize the shared httpcore2 pool or evaluate a client with native HTTP parsing and destination-indexed idle connection reuse. Preserve the canonical adapter path. The transport-only diagnostic gives a measured target without requiring a gateway rewrite
2. **Fix pool bookkeeping before tuning pool size**: avoid global connection scans and repeated socket probes where safe, reuse stable socket information, and select idle connections by origin. Preserve expiry, disconnect detection, cancellation, HTTP/2 multiplexing, and connection limits. Raising keepalive capacity alone regressed this workload
3. **Reduce observability cost while retaining accounting**: reuse stable metric attributes, reduce per-request label/aggregation work where profiling supports it, and measure faster structured-log serialization or bounded batched output. Logging and metrics are secondary costs; removing them does not close the transport gap
4. **Validate under both CPU pressure and realistic I/O**: keep the one-worker comparison, add body-consuming throughput probes, and verify HTTP/1.1, HTTP/2, streams, disconnects, timeouts, provider failures, usage records, and multiple upstream origins before promoting a change. Report CPU microseconds per request alongside CPU percentage and request rate

## Evidence and reproduction

The completed audit batches covered **590,000 timed proxied requests**, including stripped diagnostic controls, plus 31,000 warmup requests and 62 complete-response checks. Every timed/warmup request reported success. The 411,042 emitted Airmux usage records matched each applicable trial's exact expected count, successful outcome, and provider input/output token counts. Log-suppressed and bare-proxy controls do not provide equivalent usage-log evidence.

The initial log-suppression probe also hid the Uvicorn startup message required by the harness and failed readiness. That incomplete batch was discarded; the repeated batch suppresses only the data-plane logger. The failure and retained diagnostic limits are recorded in the JSON.

The JSON embeds Airmux-only diagnostic scripts under `diagnostic_sources`, with SHA-256 hashes. Install diagnostic dependencies in the active Python environment before replaying historical probes. Extract them into a writable directory mounted as `/audit` in the recorded image. Mark `gateway` executable. The scripts use the existing acceptance fixture and unchanged benchmark binaries already in the image.

```bash
docker run -d --rm --name airmux-rps-audit --network none --cpus 4 --memory 8g \
  -v /private/tmp/airmux-rps-audit:/audit \
  --entrypoint /bin/sleep sha256:949b35ffa05699e3e7d0e7f45b9d47c339a379ed99e263da8cf4056cd1387995 infinity

docker exec -e PYTHONPATH=/app:/audit airmux-rps-audit \
  /app/.venv/bin/python /audit/run.py --output /audit/ablation-v2 \
  --variants baseline:20,no_logs:20,no_metrics:20,no_observability:20,bare_proxy:20,baseline:100 --rounds 3

docker exec -e PYTHONPATH=/app:/audit airmux-rps-audit \
  /app/.venv/bin/python /audit/run.py --output /audit/transport \
  --variants baseline:20,aiohttp_buffered:20 --rounds 3

docker exec -e PYTHONPATH=/app:/audit -e AUDIT_PHASES=1 airmux-rps-audit \
  /app/.venv/bin/python /audit/phases.py --output /audit/phases \
  --variants baseline:20,aiohttp_buffered:20 --counts
```

For cProfile, use `run.py --output /audit/profile --variants baseline:20,baseline:100 --count 5000 --profile`. Pool instrumentation is selected separately with `--counts`. Never use profiled throughput as the published performance result. Full temporary artifacts are under `/private/tmp/airmux-rps-audit`; the checked-in JSON retains the measurements needed to recompute the report.
