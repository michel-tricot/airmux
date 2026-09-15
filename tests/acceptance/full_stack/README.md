# Full-stack acceptance tests

Black-box end-to-end tests. Each one stands up a real control plane, data plane and a stub
upstream in an isolated tmp dir, then drives them through the shipped console scripts and public
HTTP surfaces. Nothing here imports `control_plane` or `data_plane`; a test that needs internals
is a product gap, not a test gap.

The shared harness lives in `stack_harness.py`; `conftest.py` exposes its fixtures and Postgres setup hooks. Both
categories below use it, so a new test in either place gets the same one-line setup.

## Categories

- `scenarios/` - correctness and resilience. Does the system do the right thing under failure:
  control plane down and event replay. Asserts on behaviour and observable output.
- `benchmarks/` - manual full-stack performance sweeps. Reports percentiles and asserts lenient
  absolute limits; shared runners have made these unreliable as automatic PR checks

CI runs scenarios automatically and full-stack benchmarks only on manual dispatch. The standalone
[gateway performance job](../gateway/README.md#performance-and-regression-tracking) compares base and
candidate wheels on the same runner for every PR and main-branch push, publishes a comparison summary
and retains raw measurements for regression investigation.

## Adding a benchmark

Measure overhead as a difference, not an absolute: run the same work with and without the thing
you are measuring against the same stub upstream, and report the delta. See `benchmarks/
test_overhead.py`. Warm up before sampling, report p50/p90/p99 rather than a mean, and assert a
loose ceiling rather than an exact number.
