# Contributing to airmux

airmux is pre-1.0, so focused contributions that strengthen the current design are easier to review than broad
compatibility layers or unrelated cleanup.

Search the [issues](https://github.com/michel-tricot/airmux/issues) and open pull requests before starting. For a
substantial feature or design change, open an issue to agree on the scope with a maintainer. Bug reports should include
reproduction steps, the version or commit, expected and actual behavior, and relevant logs with credentials removed.

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

Fork [michel-tricot/airmux](https://github.com/michel-tricot/airmux) on GitHub, then clone your fork and create a branch
from the upstream `main`. Replace `YOUR-USERNAME` with your GitHub username and `describe-your-change` with a branch name:

```bash
git clone https://github.com/YOUR-USERNAME/airmux.git
cd airmux
git remote add upstream https://github.com/michel-tricot/airmux.git
git fetch upstream
git switch -c describe-your-change upstream/main
```

Contributors with repository write access may use a branch in the upstream repository instead. Keep unrelated work on
separate branches or worktrees.

Install Python 3.13 or newer, [uv](https://docs.astral.sh/uv/), Bun, and Docker with Compose. From the repository root, run:

```bash
uv sync --all-packages --frozen
bun install --frozen-lockfile
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
independent. Shared imports are limited to pure interchange values in `contract` and process infrastructure in
`airmux_runtime`.

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

Commit your change and push the branch to your fork:

```bash
git add path/to/changed-file
git commit -m "Describe the change"
git push --set-upstream origin describe-your-change
```

Replace `path/to/changed-file` with the paths you changed. On GitHub, open a **draft pull request** from that branch to
`michel-tricot/airmux:main`. Link the issue it addresses, using `Closes #<issue-number>` when it fully resolves the issue.

Keep each pull request limited to one user-visible outcome. Its description should include:

- The user or operator impact
- The design decision and important tradeoffs
- The checks and real-world verification performed
- Any documentation or generated contracts updated

When the change and local checks are complete, select **Ready for review**. PR CI runs the same fast checks on draft and ready pull requests.
Read failures in the pull request's Checks tab and use the job logs and uploaded diagnostics to investigate. Workflow
runs from forks may need [maintainer approval](https://docs.github.com/en/actions/how-tos/manage-workflow-runs/approve-runs-from-forks);
if GitHub shows that they are awaiting approval, ask a maintainer in the pull request.

Push follow-up commits to the same branch to address review feedback and rerun CI. Resolve feedback in code, tests, or
documentation, and reply to the review thread so the reviewer can confirm the change. If GitHub reports merge
conflicts, update the branch and push again:

```bash
git fetch upstream
git merge upstream/main
git push
```

Resolve any conflicts and rerun affected local checks before pushing. If you cloned the upstream repository directly,
use `origin` in place of `upstream`. A maintainer merges the pull request once it is ready, there are no merge conflicts,
the required checks pass, and review conversations are resolved. Being behind `main` alone does not require an update.
Changes enter `main` through a squash merge.

## What CI runs

[PR CI](.github/workflows/ci.yml) runs on draft and ready pull requests. It checks quality, Python unit and integration tests, frontend, and package metadata. Its `required` job passes only when all five jobs succeed. [Security](.github/workflows/security.yml) runs Python and Bun audits plus dependency review on pull requests.

[Main CI](.github/workflows/main-ci.yml) runs after merge and on manual dispatch. It repeats the five fast checks, then tests the built candidate through the gateway matrix, full-stack scenarios, Chromium, and Docker deployments. Its `required` job covers all nine jobs. [Nightly](.github/workflows/nightly.yml) checks platform compatibility and live providers on a schedule; performance and soak checks run on manual dispatch. See the [CI design](notes/design/CI.md) for the artifact and release gates.

## Main branch protection

The [versioned Protect Main ruleset](.github/policy/protect-main.json) requires a pull request and
allows squash merges only. Direct pushes, deletion, force pushes, and merge commits are blocked. Branches may merge
without being up to date with `main` when there are no merge conflicts, required checks pass, and review conversations
are resolved.

Two stable checks are required:

| Required check | Coverage |
| --- | --- |
| `required` | Quality, Python, frontend, packaged gateway, full-stack, browser, and Docker correctness |
| `dependency-security` | Python and JavaScript audits plus pull-request dependency review |

The versioned ruleset currently requires no approving reviews, but contributions still go through maintainer review.

## Releasing

Follow the [release checklist and error guide](docs/development.mdx#publish-a-release). After the version pull request merges, wait for Main CI and Security to pass on the same `main` commit, then dispatch **Publish Release**. Publishing is manual and serialized. The workflow verifies the package and container before creating the GitHub release.
