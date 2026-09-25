# Repository policy maintenance

This guide is for maintainers with repository administration access. For ordinary contributions and review, use
[CONTRIBUTING.md](../../CONTRIBUTING.md). The JSON files in this directory record the desired GitHub settings;
[scripts/github-policy](../../scripts/github-policy) compares or applies them. Workflow YAML alone does not enforce
repository settings.

## Main branch policy

[protect-main.json](protect-main.json) requires pull requests, squash merges, linear history, passing required checks,
and resolved review conversations. It blocks direct pushes, branch deletion, force pushes, and merge commits on the
default branch. The `required` and `dependency-security` checks are bound to the GitHub Actions App, integration ID
`15368`. Keep these names synchronized with the workflows and the [CI design](../../notes/design/CI.md).

PR CI runs the same five fast jobs on draft and ready pull requests. Main CI runs those jobs and the installed-candidate
acceptance jobs after merge. Each workflow's `required` gate rejects every dependency result other than success.
Security audits run on pull requests. Changes to job selection must keep the contributor guide
and workflow contract tests accurate.

The policy uses loose status checks: a conflict-free branch with passing required checks may merge without being
up to date with `main`. It does not configure a merge queue. The [CI design](../../notes/design/CI.md) records the
integration tradeoff.

## Review policy and exceptions

The checked-in policy sets `required_approving_review_count` to `0` and `require_last_push_approval` to `false`, with
stale-review dismissal enabled. These values describe enforcement, not the number of collaborators or the review
expected of contributions. When an independent reviewer is available and the project adopts required approvals, change
the count to `1` and last-push approval to `true` in a reviewed policy change. Keep stale-review dismissal enabled.

Repository administrators have a `pull_request` bypass for exceptional merges, such as unavailable required checks.
It does not permit direct pushes, branch deletion,
force pushes, or merge commits. Automation and deploy keys have no bypass. Review the change and record the reason in
the pull request before using an administrator bypass.

Repair a broken required workflow through a pull request. Ordinary merges remain blocked until required checks pass;
any administrator exception follows the process above.

## Inspect and apply policy

Use an authenticated GitHub CLI account with administration access, and install the development dependencies from
the contributor guide. Run commands from the repository root. First test the versioned policy and inspect live drift:

```bash
uv run pytest tests/ci/test_merge_policy.py tests/ci/test_github_policy.py
scripts/github-policy diff --repo michel-tricot/airmux
```

`diff` is read-only. It prints differences from live settings to the desired JSON and exits with status `1` when drift
exists. Review the output before applying: the script manages all policy files, including Actions permissions, release
tags, the release environment, deployment sources, CodeQL, and secret scanning. Feature availability depends on GitHub
repository settings and plan; investigate unsupported settings rather than assuming every policy can be applied.

For an intentional administration change, review the JSON and related documentation together in a pull request. After
that change is approved and merged, an administrator applies it from the updated `main` checkout:

```bash
scripts/github-policy apply --repo michel-tricot/airmux
scripts/github-policy diff --repo michel-tricot/airmux
```

`apply` changes live GitHub settings and finishes by checking drift. It is a separate administration action, not a
contributor setup step or an automatic consequence of editing documentation. If a policy must be reverted, restore the
previous JSON through a reviewed pull request, then inspect and apply that version with the same procedure.
