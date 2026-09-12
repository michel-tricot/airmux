# Acceptance tests

Black-box end-to-end tests. Each one stands up a real control plane, data plane and a stub
upstream in an isolated tmp dir, then drives them through the shipped console scripts and public
HTTP surfaces. Nothing here imports `control_plane` or `data_plane`; a test that needs internals
is a product gap, not a test gap.

The shared harness lives in `conftest.py` (the `stack` fixture and the `Stack` class). Both
categories below use it, so a new test in either place gets the same one-line setup.

## Categories

- `scenarios/` - correctness and resilience. Does the system do the right thing under failure:
  control plane down and event replay. Asserts on behaviour and observable output.
- `benchmarks/` - performance. Measures a cost and guards it against regression. Reports
  percentiles and asserts a lenient ceiling, so a gross regression fails but normal runner noise
  does not.

CI runs the two as separate jobs, so a slow benchmark sweep does not delay the correctness
signal and can be gated independently.

## Browser security regressions

`browser/` runs Chromium against the actual console, control plane, data plane, and synthetic
upstream. Every test gets an empty browser context, an isolated database, and dynamic local
ports. The management API seeds fixtures; login and the tested mutations go through the UI.

Install with `uv sync --all-packages --frozen`, `bun install --frozen-lockfile`, and
`uv run playwright install chromium`, then run `uv run pytest tests/acceptance/browser -q`.
The Browser security workflow runs this suite on pull requests and main pushes.
Screenshots live beside the temporary deployment logs; secret reveal inputs are masked.

## Adding a benchmark

Measure overhead as a difference, not an absolute: run the same work with and without the thing
you are measuring against the same stub upstream, and report the delta. See `benchmarks/
test_overhead.py`. Warm up before sampling, report p50/p90/p99 rather than a mean, and assert a
loose ceiling rather than an exact number.
