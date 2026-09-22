# Robyn server experiment

This experiment compares Airmux's existing Uvicorn server with Robyn 0.88.0 under the same production request path. Robyn currently adapts requests into ASGI and calls the existing Starlette application, preserving Airmux behavior while measuring the cost of using Robyn as the server.

## Method

- ARM64 Linux container on Apple M3 Max, CPython 3.13.15, one gateway worker pinned to one CPU
- One mock provider, one load generator, and one gateway CPU; no control plane
- Same Airmux configuration for both servers, including production logging, Prometheus metrics, and usage accounting to a devnull sink
- Three alternating rounds at concurrency 256, 512, and 1024; 20 seconds per measurement
- Metrics include RPS, client-observed latency, gateway CPU time per request, and peak gateway RSS
- CPU cgroup reported no throttling
- Both servers passed buffered responses, authentication failure, Anthropic Messages streaming, metrics exposure, and usage-accounting checks

## Results

Values are medians across three rounds. At concurrency 1024, Uvicorn's p99 was unstable: two runs exceeded five seconds and one was about three seconds.

| Server | Concurrency | RPS | p50 ms | p99 ms | CPU µs/request | Peak RSS MB |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Uvicorn | 256 | 3312 | 75.9 | 124.2 | 302 | 102.0 |
| Robyn ASGI adapter | 256 | 2943 | 86.4 | 136.5 | 335 | 112.6 |
| Uvicorn | 512 | 3214 | 144.7 | 228.3 | 311 | 110.9 |
| Robyn ASGI adapter | 512 | 2809 | 178.9 | 265.6 | 355 | 131.8 |
| Uvicorn | 1024 | 3090 | 161.8 | 5125.6 | 324 | 114.5 |
| Robyn ASGI adapter | 1024 | 2662 | 379.2 | 503.4 | 376 | 170.3 |

Robyn delivered 11%, 13%, and 14% less throughput at the three concurrency levels. Its CPU cost per request was 11%, 14%, and 16% higher. Peak RSS was 10%, 19%, and 49% higher. Both servers saturated the single gateway core, so the run does not point to a worker-count or CPU-quota mistake.

## Interpretation

The comparison tests the current compatibility adapter, not a native Robyn port. Each request still enters Starlette and runs the existing ASGI middleware and routes; the adapter additionally builds an ASGI scope, starts a Python task, and moves response events through an asyncio queue. This extra bridge is the likely reason for the regression. Changing process or worker settings is unlikely to remove that per-request work in a one-worker comparison.

The measurements do not establish Robyn's maximum performance with native Robyn routes. Such a port would need to replace the Starlette request path while preserving middleware, authentication, streaming, metrics, and usage behavior. This experiment does not justify adopting Robyn for throughput.
