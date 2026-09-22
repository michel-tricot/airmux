# Native Robyn server experiment

This experiment registers Airmux routes with Robyn and invokes their existing endpoints directly. Robyn handles routing and HTTP responses; the request does not pass through the Starlette ASGI application or ASGI response bridge. A lightweight Starlette `Request` and the existing response objects remain at the endpoint boundary so authentication, ingress adapters, canonical processing, provider logic, streaming, and metering stay shared.

## Method

- ARM64 Linux container on Apple M3 Max, CPython 3.13.15, one gateway worker pinned to one CPU
- One mock provider and one load generator; no control plane
- Same Airmux configuration for both servers, including production logging, Prometheus metrics, and usage accounting to a devnull sink
- Three alternating rounds at concurrency 256, 512, and 1024; 20 seconds per measurement
- Metrics include RPS, client-observed latency, gateway CPU time per request, and peak gateway RSS
- CPU cgroup reported no throttling
- Both servers passed buffered responses, authentication failure, Anthropic Messages streaming, metrics exposure, and usage-accounting checks

## Results

Values are medians across three rounds.

| Server | Concurrency | RPS | p50 ms | p99 ms | CPU µs/request | Peak RSS MB |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Uvicorn | 256 | 3051 | 83.0 | 133.9 | 328 | 102.3 |
| Native Robyn | 256 | 2990 | 83.4 | 131.8 | 332 | 109.5 |
| Uvicorn | 512 | 2978 | 163.0 | 256.3 | 336 | 111.3 |
| Native Robyn | 512 | 2957 | 172.3 | 249.0 | 338 | 126.2 |
| Uvicorn | 1024 | 2934 | 171.1 | 6190.2 | 341 | 116.2 |
| Native Robyn | 1024 | 2841 | 353.7 | 500.1 | 352 | 159.0 |

In this final run, Robyn was within 1–3% of Uvicorn's throughput at all three levels. At concurrency 1024, its median p99 was lower, while median p50 more than doubled and peak RSS was 37% higher. Both gateways saturated the same single core. A preceding paired run on the same request path showed about 4% higher Robyn throughput at 256 and 512, then 6% lower at 1024; the small throughput differences are within run-to-run variation and do not establish a general win.

The earlier ASGI-bridge implementation was 11–14% slower than Uvicorn across these load levels. Direct route invocation removed that bridge penalty, but did not eliminate the high-concurrency tradeoff.

## Interpretation

This is a native Robyn server and routing path around the existing Airmux endpoint layer, not a rewrite of canonical or provider behavior. It still constructs a Starlette `Request` value for the existing endpoint interfaces and converts their response values into Robyn responses. That preserves a single implementation of gateway behavior while removing Starlette route dispatch, ASGI app invocation, and ASGI event queueing from each request.

The result is promising enough to keep as an experiment, but does not justify replacing Uvicorn yet. The 1024-concurrency p50 and RSS regressions need investigation. A real HTTP test confirmed the upstream stream generator finalizes after an early client disconnect.
