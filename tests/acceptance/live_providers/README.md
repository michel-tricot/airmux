# Live-provider acceptance tests

Real HTTPS requests go through an installed standalone gateway to pinned OpenAI and Anthropic models.
The three egress families are OpenAI Chat Completions, OpenAI Responses, and Anthropic Messages.
All requests use canonical ingress; the Docker-free gateway suite covers the ingress dialect matrix.

The 35 scenarios progress through buffered and streaming completions, tool calls, strict JSON output,
supported Anthropic reasoning, policy denial, output limits, and cross-family fallback. A local forwarding
recorder captures native response bytes and usage without storing authentication headers. Independent
native usage readers compare every successful request's tokens and calculated prices with its usage event.
Assertions check response structure and completeness rather than exact generated text or token totals.
Fallback forces a local primary failure before calling the real secondary provider.

## Run locally

Configure `OPENAI_API_KEY` and `ANTHROPIC_API_KEY`, then run:

```bash
uv run --env-file .env pytest tests/acceptance/live_providers
```

Set `AIRMUX_GATEWAY_BIN` to an installed wheel's executable to test that build. Missing or empty keys
fail collection. Run without `-n`; one session allows at most 30 real requests, each with an output limit
of at most 1,280 tokens and an 8 KiB request body. The normal complete run makes 29 real requests.
These bounds limit test traffic; provider budgets on dedicated test keys should also be configured.

## CI and release gate

Configure `OPENAI_API_KEY` and `ANTHROPIC_API_KEY` as GitHub environment secrets in `release`.
The `live-providers` workflow runs nightly on main, on manual dispatch, and as a required job in the
Python release workflow. It is separate from ordinary PR CI because it uses credentials and incurs
provider charges. PRs still run the deterministic acceptance suites and the missing-credentials guard.

For releases, the live job downloads and installs the exact wheel that the subsequent PyPI job publishes.
Publication requires the build checks and all live-provider checks to pass in that same workflow run.
There are no skips for credentials, provider outages, or unsupported responses. A provider outage blocks
publication; rerun the failed job once it recovers. GitHub release metadata is already public when the
existing `release: published` trigger starts; the gate controls PyPI publication.

Failures appear in the Actions summary and test logs. Each run retains JUnit reports and sanitized gateway
logs, configuration, and usage events in `live-provider-test-results` for seven days. Real native response
recordings remain in test memory and are not uploaded.

## Maintain coverage

Pinned snapshots, family settings, and independent prices live in `live_harness.py`. Check provider availability
and published prices before changing them, and run the full suite against the replacement. Keep native usage
readers independent of gateway adapters and metering code so shared implementation bugs cannot pass unnoticed.
Add deterministic edge cases to the gateway suite; keep live cases focused on provider contract compatibility.

Model references: [OpenAI GPT-4.1 mini](https://developers.openai.com/api/docs/models/gpt-4.1-mini),
[Anthropic models](https://platform.claude.com/docs/en/models/overview), and
[Anthropic structured output](https://platform.claude.com/docs/en/build-with-claude/structured-outputs).
