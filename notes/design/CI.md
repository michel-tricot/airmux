# Continuous integration design

The workflow files define the checks. This record explains the boundaries that should survive a workflow change.

## Checks by event

| Workflow | Trigger | Gate | Work |
| --- | --- | --- | --- |
| [CI - Pull Request](../../.github/workflows/ci.yml) | Pull request | `required` | Quality, Python unit and integration, frontend, package metadata |
| [CI - Main](../../.github/workflows/main-ci.yml) | Main push or manual dispatch | `Main CI required` | Fast checks and one candidate build in parallel, followed by gateway, full-stack, browser, and Docker candidate validation |
| [CI - Security](../../.github/workflows/security.yml) | Pull request, main push, weekly schedule, or manual dispatch | `dependency-security` | Python and Bun dependency audits |
| [CI - Nightly](../../.github/workflows/nightly.yml) | Daily schedule or manual dispatch | None | Scheduled platform compatibility and live providers; manual performance and soak checks |
| [Release - Prepare](../../.github/workflows/prepare-release.yml) | Manual dispatch on main | None | Version-only release branch |
| [Release - Publish](../../.github/workflows/release.yml) | Version-only main push or manual dispatch on main | None | Exact-commit eligibility, installation, provider check, tag, publish, registry verification, announcement |

The Protect Main ruleset requires the CI - Pull Request `required` and CI - Security `dependency-security` checks. CI - Pull Request runs the same five jobs for draft and ready pull requests. CI - Main calls that workflow for the four non-package jobs and builds the candidate in a separate job. Its gate has a distinct display name because GitHub can treat duplicate job names across workflows as ambiguous required checks. It requires the reusable fast job, the candidate job, and every broader job. Do not add path filters that can skip a required check.

The release workflow queries successful CI - Main and CI - Security runs for its exact main commit. It checks the named gate in each run before doing release work. A failed gateway, full-stack, browser, or Docker job makes the `Main CI required` gate fail and prevents publication. Requiring a successful main run accounts for the repository's loose branch protection policy: a PR may merge with checks that predate the newest main commit.

## Candidate and publication

The PR `package` job and Main CI `candidate` job each build one source distribution and rebuild its wheel from that source distribution. They upload the candidate with `SHA256SUMS`. On main, the candidate job runs alongside the other fast checks; gateway, full-stack, browser, and Docker validation start when its artifact is ready. The main gate still requires all fast checks and candidate validation. The Docker matrix builds and tests Linux AMD64 and ARM64 images on native runners, then publishes each validated image under an architecture-specific commit tag. The container job combines their immutable digests into one manifest, verifies that it contains exactly those two platform images, and uploads the combined digest reference. Both jobs are required by the main gate.

Release - Publish downloads both artifacts directly from the successful CI - Main run by run ID and commit-specific name. Consumers verify the checksums. It does not rebuild or copy the artifacts into another run. Installation and live-provider checks finish before the protected version tag is created. PyPI uses trusted publishing; GHCR version and `latest` tags preserve the validated manifest digest. Candidate installation and published container verification run on both native architectures; the release Compose file pins the combined digest. Registry verification also includes an isolated Python install and a real gateway request before the GitHub release is announced.

Release - Publish starts automatically when a version-only commit lands on `main`. It waits for CI - Main and CI - Security on that exact commit. A manual dispatch with a source SHA is available for recovery and checks both gates immediately. Release runs are serialized so an older release cannot move `latest` after a newer one. Follow the [release checklist and error guide](../../docs/releasing.mdx) for recovery from a partial publication.

## Why these checks stay

- The branch-protection gates are stable job names, so implementation jobs can change without a ruleset edit
- Candidate checksums and the exact CI - Main run bind the release to tested bytes
- Third-party actions are pinned by full commit SHA, permissions are read-only by default, and publishing jobs receive only their needed write scopes
- Untrusted PR code has no provider or release secrets
- JUnit summaries and diagnostic artifacts survive failed jobs; evidence handling cannot replace the original failure

The gateway matrix assigns test node IDs to four shards using a stable hash. This covers newly collected cases without editing the workflow. The Docker job checks both compact and split deployments. Those checks provide broader release evidence than the PR gate while keeping PR feedback shorter.

CI - Security runs `pip-audit` and `bun audit` on both pull requests and main. Both must pass. GitHub's dependency review action currently fails for this repository because its Dependency graph is disabled, so the workflow uses the two ecosystem audits without a runtime feature probe.

CI - Nightly retains Linux and macOS Python compatibility and live-provider checks on its schedule. Performance comparisons, worker scaling, and repeated concurrency scenarios run only when CI - Nightly is dispatched manually. CI - Main already exercises both Docker deployment topologies, so CI - Nightly has no second cold Docker deployment job.

## Changing workflows

Update the focused workflow contracts in `tests/ci` and `tests/workflows` when an invariant changes. Validate workflow syntax with actionlint and ShellCheck, then run the installation check if candidate handling changed. Keep the [contributor guide](../../CONTRIBUTING.md), [release checklist](../../docs/releasing.mdx), and [repository policy guide](../../.github/policy/README.md) aligned with the executable workflow.
