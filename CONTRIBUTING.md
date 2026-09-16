# Contributing to airmux

airmux is pre-1.0, so focused contributions that strengthen the current design are easier to review than broad
compatibility layers or unrelated cleanup.

## Start with context

Read the documents closest to the change before editing code:

- [Development guide](docs/development.mdx) for setup, processes, checks, and generated contracts
- [Design records](notes/design/README.md) for the reasoning behind the control plane, data plane, credentials, and policies
- [Repository instructions](AGENTS.md) for architectural boundaries, interface rules, and delivery requirements
- [Published documentation](docs/index.mdx) for the current user-facing contract

## Document the decision

Code should make the implementation clear. Documentation should preserve context that code cannot express, including
constraints, rejected alternatives, and operational consequences.

Update the relevant design record when a change alters an architectural decision. Add a named record under
`notes/design/` when the decision has no existing home. Match the convention described in the
[design record index](notes/design/README.md).

Update the published documentation when a change affects setup, configuration, commands, APIs, behavior, deployment,
or failure modes. Keep examples runnable and describe unsupported behavior explicitly.

## Development setup

Install Python 3.13 or newer, [uv](https://docs.astral.sh/uv/), Bun, and Docker with Compose. Then run:

```bash
uv sync --all-packages --frozen
bun install --frozen-lockfile
uv run pre-commit install
docker compose -f docker-compose.dev.yml up -d --wait
```

Continue with the [development guide](docs/development.mdx) to initialize the database and run each service.

## Make a focused change

1. Start from the latest `main`
2. Add a behavior test that fails for the missing or incorrect behavior
3. Make the smallest change that establishes the intended contract
4. Update every producer, consumer, schema, example, and document affected by an interface change
5. Run focused checks while iterating, then the relevant full suites before opening a pull request

Do not add compatibility behavior for a contract that has not been deployed. Keep the control plane and data plane
independent, with `contract` as their only shared import.

## Generated contracts

Management API and canonical schema outputs are committed. Regenerate them from their owning source instead of editing generated files:

```bash
./scripts/export-openapi.sh
./scripts/generate-api-models.sh
./scripts/export-completion-schemas.sh
bun run --cwd lib/api-spec codegen
```

Commit generated outputs together with the source change.

## Validate the change

Run the checks relevant to the files you changed.

Python:

```bash
uv run ruff format --check .
uv run ruff check .
uv run ty check .
uv run lint-imports
uv run pytest -n auto
```

Console and generated TypeScript clients:

```bash
bun run format:check
bun run lint
bun run typecheck
bun run coverage
bun run --filter '@workspace/gateway-console' build
```

Documentation:

```bash
uv run pytest tests/documentation
```

Changes on the inference request path also require the acceptance scenarios and a real request against a running data plane:

```bash
uv run pytest tests/acceptance/full_stack/scenarios
```

## Open the pull request

Keep each pull request limited to one user-visible outcome. Its description should include:

- The user or operator impact
- The design decision and important tradeoffs
- The checks and real-world verification performed
- Any documentation or generated contracts updated

CI must pass before merge. Review feedback should be resolved in code, tests, or documentation rather than only explained in the discussion.

## Main branch protection

The active [Protect Main ruleset](https://github.com/michel-tricot/airmux/rules/20767120) requires a pull request and
allows squash merges only. Direct pushes, deletion, force pushes, and merge commits are blocked. Branches must be
up to date with `main` before merging, and review conversations must be resolved.

Two stable checks are required, each bound to the GitHub Actions App (integration ID `15368`):

| Required check | Coverage |
| --- | --- |
| `required` | Quality, Python, frontend, packaged gateway, full-stack, browser, and Docker correctness |
| `dependency-security` | Python and JavaScript audits plus pull-request dependency review |

These gates run even after an upstream failure. Every pull request runs the complete correctness graph without path
filters or conditional correctness skips. Failed, cancelled, missing, or unexpectedly skipped dependencies fail the
gate. Compatibility, performance, provider, soak, and cold-build checks run in `nightly.yml`. See
[continuous integration design](notes/design/CI.md).

Repository administrators may bypass the rules for pull-request merges. This keeps direct pushes, branch deletion,
force pushes, and merge commits blocked while letting an administrator merge a reviewed exception when required
checks are unavailable or strict current-base checks cannot settle during concurrent merges. Automation and deploy
keys have no bypass. Record why an administrator bypass was used in the pull request. The owner is currently the only
collaborator, so approvals are not required. When an independent collaborator with review permissions is added, set
`required_approving_review_count` to `1` and `require_last_push_approval` to `true` in the ruleset payload and apply it.
Keep stale-review dismissal enabled.

The versioned configuration is in [.github/policy](.github/policy). Workflow check names and the policy must change
together. Inspect live drift before explicitly applying it:

```bash
scripts/github-policy diff
scripts/github-policy apply
```

Use current-base status checks for this personally owned private repository. A merge queue is unavailable here.
When a required workflow is broken, repair it through a pull request; protection intentionally keeps `main` blocked
until the required checks pass. Test the gates locally with `uv run pytest tests/ci`.
