# Continuous integration design

The workflow files define the checks. This record explains the boundaries that should survive a workflow change.

## Checks by event

| Workflow | Trigger | Gate | Work |
| --- | --- | --- | --- |
| [PR CI](../../.github/workflows/ci.yml) | Pull request | `required` | Quality, Python unit and integration, frontend, package metadata |
| [Main CI](../../.github/workflows/main-ci.yml) | Main push or manual dispatch | `Main CI required` | PR checks plus gateway, full-stack, browser, and Docker candidate validation |
| [Security](../../.github/workflows/security.yml) | Pull request, main push, weekly schedule, or manual dispatch | `dependency-security` | Python and Bun audits; dependency review on pull requests |
| [Nightly](../../.github/workflows/nightly.yml) | Daily schedule or manual dispatch | None | Scheduled platform compatibility and live providers; manual performance and soak checks |
| [Prepare Release](../../.github/workflows/prepare-release.yml) | Manual dispatch on main | None | Version-only release branch |
| [Publish Release](../../.github/workflows/release.yml) | Manual dispatch on main | None | Exact-commit eligibility, installation, provider check, tag, publish, registry verification, announcement |

The Protect Main ruleset requires the PR CI `required` and Security `dependency-security` checks. PR CI runs the same five jobs for draft and ready pull requests. Main CI runs its full graph after merge, so a slow candidate check runs once for a normal change. Main CI's gate has a distinct display name because GitHub can treat duplicate job names across workflows as ambiguous required checks. It includes every main job. Do not add path filters that can skip a required check.

The release workflow queries successful Main CI and Security runs for its exact main commit. It checks the named gate in each run before doing release work. A failed gateway, full-stack, browser, or Docker job makes Main CI's `required` gate fail and prevents publication. Requiring a successful main run accounts for the repository's loose branch protection policy: a PR may merge with checks that predate the newest main commit.

## Candidate and publication

Main CI builds one source distribution and rebuilds its wheel from that source distribution. The `package` job uploads the candidate with `SHA256SUMS`. Installed-candidate gateway, full-stack, browser, and Docker jobs consume that artifact. The Docker job publishes the validated main image under a commit-specific GHCR tag and uploads its immutable digest reference.

Publish Release downloads both artifacts directly from the successful Main CI run by run ID and commit-specific name. Consumers verify the checksums. It does not rebuild or copy the artifacts into another run. Installation and live-provider checks finish before the protected version tag is created. PyPI uses trusted publishing; GHCR version and `latest` tags point to the validated main image. Registry verification includes an isolated install and a real gateway request before the GitHub release is announced.

Publishing is manual so the operator can see both main gates finish before starting. The release `prepare` job fails promptly if either gate is missing or unsuccessful. Release runs are serialized so an older release cannot move `latest` after a newer one. Follow the [release checklist and error guide](../../docs/development.mdx#publish-a-release) for recovery from a partial publication.

## Why these checks stay

- The branch-protection gates are stable job names, so implementation jobs can change without a ruleset edit
- Candidate checksums and the exact Main CI run bind the release to tested bytes
- Third-party actions are pinned by full commit SHA, permissions are read-only by default, and publishing jobs receive only their needed write scopes
- Untrusted PR code has no provider or release secrets
- JUnit summaries and diagnostic artifacts survive failed jobs; evidence handling cannot replace the original failure

The gateway matrix assigns test node IDs to four shards using a stable hash. This covers newly collected cases without editing the workflow. The Docker job checks both compact and split deployments. Those checks provide broader release evidence than the PR gate while keeping PR feedback shorter.

Security runs `pip-audit` and `bun audit` on both pull requests and main. Dependency review runs directly on pull requests because this is a public GitHub repository, where the feature is available. The `dependency-security` gate allows the review job to be skipped only on non-PR events; both ecosystem audits must always pass. See [GitHub's dependency review documentation](https://docs.github.com/en/code-security/concepts/supply-chain-security/dependency-review).

Nightly retains Linux and macOS Python compatibility and live-provider checks on its schedule. Performance comparisons, worker scaling, and repeated concurrency scenarios run only when Nightly is dispatched manually. Main CI already exercises both Docker deployment topologies, so Nightly has no second cold Docker deployment job.

## Changing workflows

Update the focused workflow contracts in `tests/ci` and `tests/workflows` when an invariant changes. Validate workflow syntax with actionlint and ShellCheck, then run the installation check if candidate handling changed. Keep the [contributor guide](../../CONTRIBUTING.md), [release checklist](../../docs/development.mdx#publish-a-release), and [repository policy guide](../../.github/policy/README.md) aligned with the executable workflow.
