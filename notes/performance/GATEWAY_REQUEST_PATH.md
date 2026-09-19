# Gateway request-path overhead, issue 292

## Findings

For a 256 KiB prompt over HTTP/1.1 at concurrency 1, median gateway overhead fell from 1.357 ms to 0.915 ms, saving 0.442 ms. Throughput rose from 388.3 to 466.8 requests/s. The decode and encode microbenchmarks independently saved 0.442 ms combined. The 256-content-event stream also improved: HTTP/1.1 completion overhead fell from 4.950 ms to 4.480 ms, and throughput rose from 175.5 to 190.8 requests/s.

Small-request throughput initially regressed at HTTP/1.1 concurrency 1, 8, and 32. The focused repeat instead improved throughput by 3.1%, 7.5%, and 1.5%. At concurrency 32, repeat overhead rose by 0.090 ms and p95 rose from 30.334 ms to 33.938 ms. These samples support the large-payload improvement but do not establish a consistent small-request latency or throughput improvement.

Worker scaling points to single-worker CPU and event-loop capacity as the primary constraint for these fast upstreams. At concurrency 32 with the default pool, HTTP/1.1 throughput rose from 1,211 to 2,378 to 2,908 requests/s with one, two, and four workers. Gateway CPU rose from 0.80 to 1.52 to 2.07 cores averaged across the observation window. Process CPU and scaling cannot distinguish Python execution cost from event-loop scheduling without profiling.

Increasing the pool from 100 to 256 had smaller, inconsistent effects across the matrix. Improvements also appeared at concurrency 32, below either limit, so pool size alone does not explain them. There is no evidence here that warrants changing the 100 total / 20 keepalive defaults. HTTP/2 throughput mostly plateaued after two workers while the provider approached one core; the HTTP/1.1 client reached 0.87 cores with four workers. The fixture and load generator constrain conclusions about further gateway capacity.

## Method

Measured on an Apple M3 Max with 14 logical CPUs and 36 GiB of memory, macOS 26.3 arm64, CPython 3.13.7, Pydantic 2.13.4, and Pydantic Core 2.46.4.

Base `862f45b1` and candidate `ae876f80` were built and installed independently with the same locked dependencies. Tests and container builds completed before the benchmarks ran sequentially. Both gateways retained structured usage logging and metrics; normal Uvicorn access logging was enabled on the base and disabled on the candidate.

The paired workloads use three alternating rounds, two-second load windows, and 20 warmup requests per connection. Small and large buffered workloads use dev-null collection. Streaming uses durable SQLite collection and verifies the exact usage-event count. The 256-event workload contains 256 content events plus finish, usage, and terminal events.

Gateway overhead is proxied mean latency minus the equally weighted means of direct-before and direct-after windows, summarized by the median across rounds. Proxied latency percentiles are reported separately. Direct-control drift and signed round estimates are retained in [the results](gateway-request-path.json); these local samples do not establish statistical significance.

The initial small-request run showed inconsistent results and slower direct controls in the weakest candidate rounds. A focused repeat covers HTTP/1.1 at concurrency 1, 8, and 32 with three alternating rounds and three-second windows. Both runs are retained. A CPU snapshot during measurement also showed substantial unrelated system activity, including Bluetooth and audio services; small differences should be treated cautiously.

## Codec microbenchmarks

Median of five repetitions of 2,000 operations. Provider encoding includes model dumping and alias mapping, not just JSON serialization. Decode and encode sizes describe prompt content; HTTP JSON framing adds bytes. The stream size describes the event payload.

| Operation | Payload bytes | Before (µs) | After (µs) | Saved (µs) |
| --- | ---: | ---: | ---: | ---: |
| request_decode | 2 | 0.912 | 0.243 | 0.669 |
| provider_encode | 2 | 2.141 | 1.466 | 0.675 |
| request_decode | 262144 | 198.904 | 15.153 | 183.751 |
| provider_encode | 262144 | 341.734 | 83.157 | 258.577 |
| stream_parse_validate | 69 | 2.125 | 1.431 | 0.694 |

## Paired gateway measurements

Small uses a two-byte prompt, large uses 256 KiB, and stream uses 256 content events. An asterisk marks an overhead estimate whose round range or control drift triggers the harness noise diagnostic. Negative estimates reflect control, queueing, or connection-topology differences and do not represent negative code execution cost.

| Workload | Provider | Concurrency | Before RPS | After RPS | RPS change | Before overhead (ms) | After overhead (ms) | Overhead change (ms) | Before p95 (ms) | After p95 (ms) |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| small | http1 | 1 | 971.5 | 824.1 | -147.4 | 0.660 | 0.781 | +0.121 | 1.451 | 1.565 |
| small | http1 | 8 | 1590.2 | 1262.8 | -327.4 | 2.863 | 3.737 | +0.874 | 6.661 | 8.394 |
| small | http1 | 32 | 1248.4 | 994.9 | -253.5 | 17.043 | 22.759 | +5.716 | 31.383 | 45.198 |
| small | http1 | 128 | 1117.1 | 1195.9 | +78.8 | 79.866 | 69.464 | -10.402 | 199.575 | 185.740 |
| small | http2 | 1 | 556.2 | 542.5 | -13.7 | 0.803 | 0.806 | +0.003 | 2.416 | 2.455 |
| small | http2 | 32 | 1098.5 | 1119.9 | +21.4 | 10.752 | 9.150 | -1.603 | 34.458 | 32.593 |
| small | http2 | 128 | 1030.7 | 1106.8 | +76.0 | 43.504 | 40.417 | -3.087 | 145.477 | 137.878 |
| large | http1 | 1 | 388.3 | 466.8 | +78.6 | 1.357 | 0.915 | -0.442 | 3.168 | 2.525 |
| large | http1 | 8 | 766.9 | 1099.7 | +332.8 | 3.760 | 0.620 | -3.140 | 12.453 | 8.666 |
| large | http1 | 32 | 649.7 | 1036.5 | +386.9 | 20.802 | 3.694 | -17.108 | 67.596 | 38.811 |
| large | http1 | 128 | 637.2 | 939.3 | +302.1 | 88.572 | 25.133 | -63.439 | 309.221 | 193.851 |
| large | http2 | 1 | 167.4 | 187.1 | +19.7 | 1.623 | 0.883 | -0.741 | 7.103 | 6.200 |
| large | http2 | 32 | 205.3 | 244.6 | +39.3 | 14.973* | -10.876* | -25.849 | 234.276 | 190.135 |
| large | http2 | 128 | 189.0 | 230.1 | +41.1 | 42.744* | -31.000* | -73.744 | 898.664 | 762.419 |
| stream | http1 | 1 | 175.5 | 190.8 | +15.3 | 4.950 | 4.480 | -0.470 | 6.489 | 5.846 |
| stream | http2 | 32 | 220.5 | 265.9 | +45.4 | 104.314 | 80.190 | -24.124 | 194.998 | 128.659 |
| small-repeat | http1 | 1 | 999.6 | 1030.5 | +31.0 | 0.634 | 0.589 | -0.045 | 1.373 | 1.276 |
| small-repeat | http1 | 8 | 1627.8 | 1750.5 | +122.7 | 2.759 | 2.431 | -0.329 | 6.144 | 5.860 |
| small-repeat | http1 | 32 | 1323.3 | 1343.8 | +20.5 | 15.558 | 15.648 | +0.090 | 30.334 | 33.938 |

First-content overhead for the dense stream is reported separately from total completion latency:

| Provider | Concurrency | Before first-content overhead (ms) | After first-content overhead (ms) |
| --- | ---: | ---: | ---: |
| http1 | 1 | 3.551 | 3.073 |
| http2 | 32 | 80.256 | 62.494 |

## Worker and pool matrix

Three rounds cover all 24 combinations. Keepalive stays at 20 per worker, and timeouts and expiry are unchanged. Caller traffic is HTTP/1.1. HTTP/2 direct controls use one connection; proxied traffic can use one per gateway worker. CPU averages cover client setup, warmup, load, and teardown. Connection counts are distinct provider connections used over that window, including churn, rather than peak simultaneous sockets. The linked JSON also retains p50 and p99 latency and the direct-control drift for every case.

| Workers | Pool limit | Concurrency | Provider | RPS | p95 (ms) | Overhead (ms) | Gateway cores | Provider cores | Client cores | Provider connections |
| ---: | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 100 | 32 | http1 | 1211.4 | 33.151 | 17.411 | 0.80 | 0.06 | 0.40 | 101 |
| 1 | 100 | 32 | http2 | 1092.2 | 35.714 | 10.793 | 0.85 | 0.61 | 0.41 | 1 |
| 1 | 100 | 128 | http1 | 1060.4 | 207.939 | 79.772 | 0.80 | 0.05 | 0.34 | 883 |
| 1 | 100 | 128 | http2 | 913.5 | 192.272 | 58.055 | 0.85 | 0.59 | 0.40 | 1 |
| 1 | 256 | 32 | http1 | 1298.9 | 33.680 | 14.534 | 0.79 | 0.06 | 0.40 | 114 |
| 1 | 256 | 32 | http2 | 1195.9 | 30.811 | 8.588 | 0.86 | 0.62 | 0.42 | 1 |
| 1 | 256 | 128 | http1 | 1196.2 | 173.439 | 70.512 | 0.81 | 0.06 | 0.34 | 1368 |
| 1 | 256 | 128 | http2 | 1032.9 | 135.507 | 48.616 | 0.84 | 0.58 | 0.40 | 1 |
| 2 | 100 | 32 | http1 | 2378.1 | 21.784 | 4.732 | 1.52 | 0.12 | 0.71 | 54 |
| 2 | 100 | 32 | http2 | 1796.0 | 24.979 | -0.511 | 1.62 | 0.86 | 0.67 | 2 |
| 2 | 100 | 128 | http1 | 2127.1 | 109.309 | 23.955 | 1.38 | 0.09 | 0.59 | 1048 |
| 2 | 100 | 128 | http2 | 1533.7 | 146.301 | 9.093 | 1.38 | 0.81 | 0.57 | 2 |
| 2 | 256 | 32 | http1 | 2378.4 | 21.616 | 4.573 | 1.52 | 0.12 | 0.71 | 58 |
| 2 | 256 | 32 | http2 | 1837.2 | 22.078 | -0.460 | 1.64 | 0.87 | 0.67 | 2 |
| 2 | 256 | 128 | http1 | 2099.5 | 115.398 | 23.542 | 1.35 | 0.09 | 0.59 | 988 |
| 2 | 256 | 128 | http2 | 1725.6 | 117.013 | 1.137 | 1.41 | 0.81 | 0.57 | 2 |
| 4 | 100 | 32 | http1 | 2908.0 | 19.096 | 2.445 | 2.07 | 0.17 | 0.87 | 32 |
| 4 | 100 | 32 | http2 | 1761.8 | 34.952 | -0.276 | 1.92 | 0.89 | 0.68 | 4 |
| 4 | 100 | 128 | http1 | 2790.3 | 111.478 | 11.742 | 1.96 | 0.13 | 0.78 | 1141 |
| 4 | 100 | 128 | http2 | 1751.9 | 169.213 | -0.496 | 1.63 | 0.83 | 0.61 | 4 |
| 4 | 256 | 32 | http1 | 2918.0 | 20.731 | 2.180 | 2.16 | 0.17 | 0.87 | 32 |
| 4 | 256 | 32 | http2 | 1847.3 | 37.391 | -0.698 | 1.92 | 0.87 | 0.68 | 4 |
| 4 | 256 | 128 | http1 | 3022.2 | 111.105 | 9.147 | 1.84 | 0.13 | 0.74 | 1266 |
| 4 | 256 | 128 | http2 | 1747.8 | 180.176 | -2.810 | 1.68 | 0.84 | 0.63 | 4 |

## Reproduction

Use the commands in the [benchmark guide](../../tests/acceptance/gateway/README.md#codec-and-capacity-experiments), with `--rounds 3 --duration-s 2 --warmup 20` for the paired measurements. The focused repeat calls the same `run_round` harness with `Settings(3, 20, 0, scenario="buffered_devnull", concurrency=concurrency, provider_protocol="http1")` for concurrency 1, 8, and 32, alternating base/candidate order over three rounds.

The full local raw artifacts are under `/private/tmp/airmux-292/{small,small-repeat,large,stream,scaling}`. The checked-in JSON preserves codec timings, aggregate comparisons, signed overhead estimates for every paired round, scaling summaries, and per-round CPU observations. Nightly CI retains full raw artifacts for 90 days.
