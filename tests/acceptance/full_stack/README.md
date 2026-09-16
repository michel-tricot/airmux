# Full-stack acceptance tests

Black-box tests start real control-plane and gateway processes and drive the shipped console scripts and public HTTP
surfaces. Each scenario gets an isolated directory and Postgres database. Security scenarios that exercise only
management APIs start only the control plane. Nothing imports `control_plane` or `data_plane`.

`stack_harness.py` owns deployment setup and an authenticated HTTP provider; `conftest.py` exposes its fixture and
Postgres lifecycle hooks. API scenarios live in `scenarios/`, while `browser/` drives the console through Chromium.
Both run on every PR update and push to main. The scenario controller starts one Postgres server and xdist workers
create isolated databases and state directories inside it:

```bash
uv run pytest -n 2 tests/acceptance/full_stack/scenarios
uv run playwright install chromium
uv run pytest tests/acceptance/full_stack/browser
```

Keep scenarios here when they prove a boundary that standalone gateway tests cannot: remote bundle publication,
organization/workspace isolation, credential resolution, transactional security races, outage operation and durable
export into the control plane. Protocol details, SDK decoding and local bundle setup belong in the
[standalone suite](../gateway/README.md).

Browser scenarios cover boundaries that component tests cannot prove: one-time credential handling, navigation and
authorization against real services, inference recovery, and server-side membership revocation with reload recovery.

Event replay uses real inference events. A forwarding HTTP proxy commits the first batch into the control plane, then
returns an unavailable response instead of its acknowledgement. The test observes identical event IDs delivered again,
exactly one stored event per ID and an empty public pending queue. It never inserts synthetic events into SQLite.
Concurrent export requires all 128 requests to succeed across four configured gateway workers and all events to arrive
with unique event and request IDs. This is a correctness scenario, not a throughput benchmark. Workers share one
heartbeat identity, so the instance roster does not reveal individual worker readiness.

Authentication resilience checks malformed input and saturates a real password worker with a bounded queue. Health
and inference requests run concurrently with authentication bursts; a valid login must work again afterwards.

The Actions summary displays counts and expandable assertion/setup failures even when pytest fails. The
`full-stack-acceptance` artifact retains JUnit XML and per-scenario control-plane, gateway, CLI setup and stub-upstream
logs for seven days. Set `AIRMUX_STACK_ARTIFACTS` to a directory to retain these logs locally. Teardown copies only the
named logs after stopping services and redacts known test credentials. Configuration, cookies, private keys and secret-store
files are excluded. Stub logs contain request counts, timestamps and HTTP statuses without headers or bodies.

The previous absolute-threshold overhead and throughput sweeps have been retired. The nightly
[gateway performance job](../gateway/README.md#performance-and-regression-tracking) compares base and candidate wheels
on the same runner. Its event writes are included, but control-plane polling and export
traffic are not measured. Full-stack scenarios protect remote operation and export correctness; add a separate
performance workload before making claims about remote/export latency or worker scaling.
