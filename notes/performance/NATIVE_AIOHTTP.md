# Native aiohttp transport

The data plane now uses aiohttp directly. In three alternating same-container rounds, throughput increased **38.2%** and gateway CPU per request fell **54.2%** relative to the preceding HTTPX2 implementation. Both revisions already include the credential-cache and stream-accumulation optimizations. Authentication, canonical translation, accounting, metrics, and structured usage logs remain enabled.

| Metric | HTTPX2 before | Native aiohttp |
| --- | ---: | ---: |
| Requests/s, concurrency 64 | 1,408 | 1,945 |
| Gateway CPU, 100% = one core | 90.1 | 59.2 |
| Gateway CPU per request, µs | 641.5 | 294.0 |
| Complete-response p99, concurrency 16, ms | 39.59 | 33.67 |
| Response-header p99, concurrency 64, ms | 73.91 | 53.54 |
| Idle startup RSS, decimal MB | 82.2 | 86.9 |
| Peak sampled RSS, decimal MB | 86.6 | 89.6 |

These are medians of three trials. Latency includes the local mock's 20 ms upstream delay. The complete-response p99 and throughput probes have different concurrency and timing boundaries. They must not be presented as one operating point or as the gateway's intrinsic p99 overhead. The median difference between the aiohttp complete-response p99 and bracketed direct controls was 0.45 ms; subtracting percentiles does not measure the p99 of individual gateway overhead.

## Native transport behavior

Each worker owns one aiohttp session and connector, with 100 active connections by default and native destination-specific reuse. Idle connections expire after 15 seconds; the previous separate idle-count limit has been removed. There is no HTTPX compatibility layer, transport switch, custom pool, or replacement SSE parser. HTTPX2 remains a development dependency for independent benchmark clients.

Provider bodies are serialized once into bytes and sent directly. Buffered responses are read once. Streaming consumes available byte chunks through `iter_any()` and retains the existing canonical framing, partial finalization, and cancellation accounting. Native flow control pauses provider reads when downstream consumption stops. Closing a stream frees its connector slot without waiting for provider EOF. Provider cookies are disabled and redirects are not followed.

Environment proxy support is enabled only when an HTTP or HTTPS proxy is configured at startup. The normal direct path therefore avoids aiohttp's per-request executor work for proxy and netrc lookup. Remote control-plane responses must complete and return a 2xx status before being accepted, including usage export acknowledgements.

Outbound transport is HTTP/1.1, including TLS. The current benchmark harness uses HTTP and HTTPS with HTTP/1.1 on both direct and proxied paths. Connect/pool acquisition share a five-second timeout; reads have a 120-second idle timeout. There is no independent write timeout or overall inference timeout. Budget refresh retains a five-second total deadline. See [configuration](../../docs/reference/configuration.mdx#outbound-http-connections).

## Streaming comparison

| Workload | Previous CPU/request | aiohttp CPU/request | Previous completion p50 | aiohttp completion p50 |
| --- | ---: | ---: | ---: | ---: |
| 256 KiB / 4,096 fragments | 36.0 ms | 36.0 ms | 53.4 ms | 52.0 ms |
| 8 MiB / 8,192 fragments | 93.0 ms | 87.0 ms | 129.6 ms | 131.7 ms |

Each stream trial consumes and verifies ten complete responses after two warmups at concurrency one. There are three alternating rounds per workload. The larger payload is a stress case. These short probes establish correctness and approximate CPU costs, not stable streaming tail latency. First-content and memory observations are retained in the JSON.

## Method and evidence

The [measurements](native-aiohttp.json) retain every trial summary, direct controls, source hashes, and executable diagnostic scripts. Full resource samples and process logs are also retained locally under `/private/tmp/airmux-native-aiohttp`.

- Previous revision: `6d56c2a1ea015f5bd7d66de15a6ce5e64462521c`
- One proxy worker, local bundle, no control-plane server or database, devnull event sink
- Same Linux ARM64 Docker image for both variants, four allocated CPUs, 8 GiB memory, loopback only, `--network none`
- Image: `sha256:949b35ffa05699e3e7d0e7f45b9d47c339a379ed99e263da8cf4056cd1387995`
- CPython 3.13.15, HTTPX2 2.13.0, aiohttp 3.14.3, native compiled aiohttp wheels
- Same benchmark drivers for both Airmux variants, with a 20 ms Anthropic mock
- Throughput: 20,000 requests at concurrency 64 after 1,000 warmups; official Rust driver measures response headers
- Latency: 5,000 requests at concurrency 16; official Python driver consumes each response body
- Two additional complete-response checks per buffered trial verify text and provider token accounting
- Direct controls bracket each alternating round; gateways, providers, and load drivers run sequentially without concurrent test runs
- Gateway CPU is process-tree user plus system CPU; driver, provider, and sampler CPU are excluded
- Idle memory is median RSS from ten samples after readiness and before inference; peak memory is sampled every 50 ms
- 156,156 successful usage records verified across buffered and streaming trials, with no benchmark HTTP errors

The baseline uses its existing 100-total/20-idle pool with five-second idle expiry. The candidate uses native aiohttp pooling. These results measure the complete shipped migration, not transport-library cost with every pool behavior held constant. Three laptop rounds do not establish production capacity or statistical confidence bounds.

Validation covers 910 data-plane, contract, and runtime checks; 593 real-gateway acceptance checks; 44 benchmark-harness checks including TLS; documentation/CLI/CI contract checks; four installed-wheel checks including buffered and streaming requests; Ruff, ty, lock consistency, and import boundaries. Real-socket regressions cover connection reuse, cookie isolation, cancellation releasing a saturated pool, timeout recovery, proxy routing, netrc isolation without proxies, bounded streaming reads, and retained usage events after redirects or truncated acknowledgements. The test fixture supplies the stream writer missing from aioresponses 0.7.9's response constructor, tracking [upstream issue 289](https://github.com/pnuckowski/aioresponses/issues/289); real-network acceptance does not use this mock.

## Reproduction

Extract `diagnostic_sources` from the JSON into a directory mounted as `/audit`, make `gateway` executable, archive the baseline sources into `/baseline`, and mount the candidate checkout at `/candidate`. Install the aiohttp 3.14.3 Linux wheels and their dependencies into `/audit/aiohttp-deps` before disabling networking. Both variants use the image's original benchmark binaries and drivers.

```bash
docker exec -e PYTHONPATH=/app:/audit airmux-native-aiohttp \
  /app/.venv/bin/python /audit/run.py --output /audit/buffered \
  --variants baseline:20,aiohttp:0 --rounds 3

docker exec -e PYTHONPATH=/app:/audit airmux-native-aiohttp \
  /app/.venv/bin/python /audit/streams.py run --output /audit/streams --rounds 3
```

The descriptor's `aiohttp:0` suffix is an unused diagnostic label, not a zero connection limit. Its actual configuration contains only `max_connections: 100`. The sources and data preserve that distinction.
