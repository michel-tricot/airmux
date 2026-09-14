# Contributing to TokKeeper

TokKeeper is pre-1.0, so focused contributions that strengthen the current design are easier to review than broad
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
uv run pytest tests/acceptance/scenarios
```

## Open the pull request

Keep each pull request limited to one user-visible outcome. Its description should include:

- The user or operator impact
- The design decision and important tradeoffs
- The checks and real-world verification performed
- Any documentation or generated contracts updated

CI must pass before merge. Review feedback should be resolved in code, tests, or documentation rather than only explained in the discussion.
