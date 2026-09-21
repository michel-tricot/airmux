# Data-plane CPU review

The fresh request-path review found two application costs that grow unnecessarily: credential-cache cleanup scans unrelated credentials on each request, and several streaming adapters repeatedly copy the entire accumulated response. The implementation bounds cleanup frequency and accumulates stream fragments in lists. HTTPX2, validation, policy evaluation, accounting, logs, and metrics remain enabled.

Three alternating rounds against the unchanged gateway produced these medians on the same laptop and Docker image:

| Workload | Previous CPU/request | Updated CPU/request | CPU reduction |
| --- | ---: | ---: | ---: |
| Buffered, one warm credential | 710 µs | 658.5 µs | 7.3% |
| Buffered, 4,096 unrelated warm credentials | 1,623.5 µs | 707.5 µs | 56.4% |
| Stream, 256 KiB in 4,096 fragments | 50 ms | 37 ms | 26.0% |
| Stream stress case, 8 MiB in 8,192 fragments | 851 ms | 94 ms | 89.0% |

These are workload-specific improvements, not a universal overhead or capacity claim. The 8 MiB response is deliberately a stress case. The ordinary buffered workload improved from 1,310 to 1,381 requests/s; the larger credential cache improved from 604 to 1,323 requests/s. Its prior throughput penalty largely disappears after the cleanup change. Every paired round reduced CPU in each workload.

The [measurements and diagnostic source](data-plane-cpu-review.json) include all trials, direct controls, warmups, source hashes, and the failing baseline regression output. CPU is gateway process CPU divided by completed requests. It includes both user and kernel execution and excludes CPU consumed by the separate provider and load driver.

## Credential cleanup

`CredentialResolver.available()` and `fetch()` both called `_prune()`. Each call copied and scanned the entire credential-value and cooldown dictionaries, even when all entries were unexpired. A request using one credential therefore paid for every other recently used credential on the worker.

Cleanup now runs at most once per second when requests access the resolver. The existing per-entry expiry checks still run on every lookup, including inside the single-flight lock. Negative-cache expiry, version-based rotation, explicit invalidation after credential rejection, and cooldown selection keep their existing semantics. Expired entries can remain allocated until the next sweep; they cannot become usable because cleanup was deferred. Cleanup still needs a full scan once per interval, so its occasional cost remains proportional to cache size.

The large-cache experiment seeds the same 4,096 unrelated unexpired entries into both revisions before requests begin. This isolates cache cardinality from policy count, provider count, and credential-store I/O. It does not represent 4,096 simultaneous provider requests or a measured multi-tenant production deployment.

## Stream accumulation

Anthropic text, reasoning, signatures, and tool arguments; OpenAI tool arguments; and OpenAI Responses text, reasoning, and tool arguments used repeated string concatenation in stream state. Responses ingress and Anthropic signature rendering had the same pattern. Appending a fragment could copy everything already received, making total work quadratic as responses grew.

These fields now append fragments and join them when a complete or partial response is needed. OpenAI text and reasoning already followed this pattern and remain unchanged. There is no new accumulator abstraction or dependency. SSE framing, canonical chunks, event ordering, per-event delivery, and the timing of upstream reads are unchanged. Finalization still returns a valid snapshot after any prefix and does not consume the accumulated fragments.

For the 256 KiB stream, median completion latency fell from 65.9 to 53.8 ms. For the 8 MiB stress case, it fell from 920.7 to 127.3 ms. First-content medians remained around 5 ms in these local probes; these small samples do not establish a precise first-token latency change.

The fragment lists retain references and have per-fragment memory overhead. Sampled peak gateway RSS did not regress in these workloads: 84.9 to 84.3 MB for the 256 KiB stream, and 116.0 to 101.4 MB for the stress case. Sampling every 50 ms can miss short allocation peaks. These measurements do not establish a memory bound for arbitrarily fragmented streams.

## Review of the rest of the path

| Area | Assessment |
| --- | --- |
| Authentication and bundle state | Keys, providers, models, profiles, and credentials already have bundle-time indexes; retain direct lookups and per-request expiry checks |
| Routing, policies, and budgets | Matching rules are compiled and budget state is local; preserve policy and capability validation instead of caching decisions across changing requests |
| Canonical translation and JSON | The existing Pydantic Core codec changes cover inference boundaries; preserve the canonical waist and validation at untrusted boundaries |
| Metering | Exact decimal costs and cancellation accounting are required behavior; durable outboxes already batch work on a storage thread |
| Logs and metrics | The earlier controls identified secondary costs; retain observability instead of introducing a second aggregation or logging pipeline |
| Outbound HTTP | The earlier audit still identifies the main remaining small-request cost in HTTPX2/httpcore2; retain HTTP/2, proxy, timeout, cancellation, and error behavior |

The [transport audit](GATEWAY_THROUGHPUT_AUDIT.md) remains relevant. A temporary aiohttp substitution reduced transport CPU, but that prototype lacked equivalent HTTP/2 and failure-path coverage. Shipping a second transport, a private pool implementation, or a runtime monkeypatch would increase maintenance and reliability risk. The small socket-reference optimization remains a candidate for an upstream-reviewed release. Per-origin pools address mixed-provider isolation; they do not address this single-origin benchmark. HTTP/2 is already enabled and was not disabled to obtain these numbers.

## Method and verification

The baseline is commit `e474cab9`; its data-plane and runtime sources match `d2dd6c47322360c3d81c2c5d2c972664ea1b638b`. Every baseline Python source file in the image was compared with the committed archive. The candidate uses the source hashes recorded in the JSON. Both use image `sha256:949b35ffa05699e3e7d0e7f45b9d47c339a379ed99e263da8cf4056cd1387995`, one worker, four allocated CPUs, 8 GiB, and no external network.

Buffered trials use the unchanged official Rust driver, 20,000 requests at concurrency 64, 1,000 warmups, and the 20 ms Anthropic mock. Direct controls bracket each round. That driver measures response headers; two additional complete-response checks per trial verify text and token accounting. Stream trials use a body-consuming Python driver, ten measured requests and two warmups per trial at concurrency one. A separate local provider returns fixed Anthropic SSE bytes. Both paths verify the complete text, final event, and reported token counts. Stream CPU totals include the short period needed to launch and exit the separate load driver; CPU/request is the useful comparison, rather than utilization during that window.

The completed batches contain 240,120 timed gateway requests, 12,024 warmups, 168 complete-response checks including the streaming requests and warmups, and 252,168 verified usage records. All succeeded. The first streaming attempt completed two warmups and then failed to import a test helper in its child driver; it was excluded and rerun after correcting that diagnostic import path.

Regression tests were written and run before the implementation. Six baseline cases failed: credential-cache scaling and five stream-accumulation cases. OpenAI text accumulation already passed. The tests use median thread CPU time and generous scaling ratios, rather than an absolute machine-speed threshold. Behavior checks cover positive and negative expiry between sweeps, cache retirement, cooldown recovery, and repeated partial finalization. The full data-plane, contract, and runtime suites passed 914 checks. The complete real-gateway acceptance suite passed 593 checks, covering the protocol matrix, streaming, errors, disconnects, fallback, metering, and reload behavior. Ruff, `ty check .`, and 130 documentation checks also passed.

To reproduce, extract the JSON's `diagnostic_sources` into a directory mounted as `/audit`, make `gateway` executable, and mount the candidate checkout read-only as `/candidate` in the image:

```bash
docker run -d --rm --name airmux-cpu-review --network none --cpus 4 --memory 8g \
  -v /private/tmp/airmux-cpu-review:/audit \
  -v "$PWD":/candidate:ro \
  --entrypoint /bin/sleep sha256:949b35ffa05699e3e7d0e7f45b9d47c339a379ed99e263da8cf4056cd1387995 infinity

docker exec -e PYTHONPATH=/app:/audit airmux-cpu-review \
  /app/.venv/bin/python /audit/run.py --output /audit/buffered \
  --variants baseline:20,candidate:20,baseline_many:20,candidate_many:20 --rounds 3

docker exec -e PYTHONPATH=/app:/audit airmux-cpu-review \
  /app/.venv/bin/python /audit/streams.py run --output /audit/streams --rounds 3
```
