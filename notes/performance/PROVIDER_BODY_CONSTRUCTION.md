# Provider request construction after canonical validation

OpenAI Chat and Anthropic Messages now build outbound bodies as `TypedDict` values. Their fields are still mapped explicitly from validated canonical requests. This removes the second Pydantic model construction and its recursive `model_dump` copy. OpenAI Responses already constructed a dictionary. The common encoder retains its alias mapping, typed-field precedence, top-level null omission, and passthrough handling.

A comparison across 432 corpus, adapter, stream, alias, and passthrough combinations matched body bytes, URLs, headers, and rejection outcomes. New tests cover nested schema nulls, large integers, Unicode, non-finite extension encoding, and request immutability. The allocation regression failed for Chat and Messages before the change and passes for every adapter afterward.

## Measurements

Three alternating rounds compare the logging branch (`51a04992`) with this change in the same offline Linux ARM64 container: one gateway worker, four allocated CPUs, 8 GiB, no control-plane server or database, metrics and batched structured logs enabled, and a devnull usage sink. Each round sends 5,000 requests after 1,000 warmups, at concurrency 64, to a 20 ms mock provider. Each request contains 32 tools with 64 schema properties each, about 244 KB of JSON.

| Metric, median across rounds | Parent | Candidate |
| --- | ---: | ---: |
| Gateway CPU/request | 2.892 ms | 1.978 ms |
| Requests/s | 267 | 391 |
| Complete-response p99 | 365.0 ms | 238.6 ms |

Paired CPU reductions were 32.0%, 31.3%, 31.9%. These are tool-heavy workload results, not a general gateway overhead claim. P99 includes provider delay and queuing at this concurrency. This workload uses an aiohttp driver that consumes complete bodies and checks token counts, not the earlier Rust driver that times response headers. Parent and candidate use the same driver, and direct-provider controls bracket each round. All 36,012 expected usage records were retained with unique request IDs and matching token counts.

The isolated host probe measured about 65% lower translation CPU for the tool-heavy Chat and Messages requests. Peak temporary allocations fell from 820–833 KB to about 245 KB. These are allocations during translation, not idle process RSS. Small requests saved about 2 microseconds in the isolated translation probe; this investigation does not establish a small-request end-to-end throughput improvement.

Validation: 1,064 runtime, contract, data-plane, and documentation checks; 594 real-gateway acceptance checks; 44 performance-harness checks; Ruff and ty. [Raw measurements and reproduction sources](provider-body-construction.json) include every timed trial and control, source hashes, the differential probe, and the load driver.
