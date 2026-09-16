# Acceptance tests

Black-box tests drive real processes through the shipped console scripts and public HTTP surfaces.
The suites keep separate harnesses and CI jobs:

- [Gateway](gateway/README.md): standalone gateway scenarios, protocol variations, policies, metering,
  and performance comparisons, without a control plane, Postgres, or Docker
- [Live providers](live_providers/README.md): pinned OpenAI and Anthropic requests, native usage and pricing
  verification, run nightly, manually, and as a prerequisite for PyPI releases
- [Full stack](full_stack/README.md): control plane and gateway scenarios, including authentication,
  bundle publication, organization isolation, event export, and replay, with a throwaway Postgres server

Run either suite from the repository root:

```bash
uv run pytest tests/acceptance/gateway -n auto
uv run pytest tests/acceptance/full_stack/scenarios
```

Both correctness suites and the gateway performance comparison run on PR updates and pushes to main.
Each suite owns its `conftest.py`; gateway tests do not load full-stack setup. Both correctness jobs
publish assertion failures in their Actions summary and retain JUnit XML as downloadable artifacts.
