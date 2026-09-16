# CI change policy and timing

Pull requests always start the CI, Docker, and dependency-security workflows. A reusable change-policy job computes a complete, NUL-delimited Git diff once per CI or Docker workflow, using the PR's base and head SHAs and their merge base. Rename detection is disabled so both the old and new paths invalidate checks. Missing revisions and classifier errors fail validation rather than authorizing skips.

| PR paths | Documentation and workflows | Frontend and client drift | Backend, packaging and acceptance | Docker |
| --- | --- | --- | --- | --- |
| `docs/`, `notes/`, `README.md`, `CONTRIBUTING.md`, `docs.json` only | Run | Skip | Skip | Skip |
| `apps/console/`, `lib/api-client-react/` only, optionally with documentation | Run | Run | Skip | Run |
| Backend, API specification, shared contract, taxonomy, packaging, lockfiles, package manifests, scripts, workflows, infrastructure, or unknown paths | Run | Run | Run | Run |

Frontend edits retain Docker coverage because deployment images include the console. Backend and API edits retain frontend generation checks because they can change the generated client. Empty diffs select full validation. Main pushes and manual candidate validation always select full validation; release and live-provider workflows retain their existing unfiltered coverage.

Dependency audits and gateway-performance reporting run on every PR and main push. Performance warnings remain advisory, and the benchmark implementation and cadence belong to #173. Full-stack acceptance remains sequential until its Postgres lifecycle supports safe worker sharing.

The `ci` and `deployment-results` aggregates must succeed before merging. They require a successful classifier, every expected dependency, valid policy outputs, and successful necessary jobs. Skips pass only when the policy permits them; failures and cancellations fail even for optional work that started. `gateway-results` also rejects failed or cancelled installation and gateway jobs before summarizing artifacts. Branch protection is managed separately by #178; individual skipped jobs are insufficient merge gates.

Dependency-security concurrency includes the workflow name and PR number. Only PR runs cancel in-progress predecessors. Non-PR runs use ref, SHA, and run ID so scheduled, manual, main, and release-candidate runs cannot replace each other, including pending runs.

## Timing evidence

Baseline: successful PR runs for `codex/fix-readiness-prompts` on 2026-09-16 UTC, after gateway sharding. Timings come from the Actions jobs API: queue time is `started_at - created_at`, execution is `completed_at - started_at`. Dependency waiting is separate from runner queue time. Workflow elapsed time includes queueing, dependency waiting, and reporting.

| Workflow | Run | Workflow elapsed | Longest job execution | Runner queue per job |
| --- | --- | --- | --- | --- |
| CI | [35048133470](https://github.com/michel-tricot/airmux/actions/runs/35048133470) | 286 s | Backend 282 s | 2 to 3 s |
| Docker | [35048133515](https://github.com/michel-tricot/airmux/actions/runs/35048133515) | 173 s | Split deployment 169 s | 3 s |
| Security | [35048133513](https://github.com/michel-tricot/airmux/actions/runs/35048133513) | 22 s | Python audit 19 s | 3 s |

The longest sampled gateway shard executed for 166 s; frontend took 144 s, installation 53 s, full-stack acceptance 243 s, and performance comparison 218 s. A roughly five-minute ordinary PR is a target, not a guarantee. Docs-only savings remain bounded by the every-PR performance comparison.

The first obsolete security run, [35048719555](https://github.com/michel-tricot/airmux/actions/runs/35048719555), was cancelled at 02:38:00 UTC after the second PR push, 13 s after creation. Its replacement was queued independently. Non-PR isolation and PR-only in-progress cancellation are covered by the workflow policy test.

After-change sample: PR #189, revision `7e0d1714`, on 2026-09-16 UTC. Workflow and script edits intentionally select full validation, so this comparison measures scheduling overhead and runner availability rather than docs-only savings.

| Workflow | Run | Workflow elapsed | Longest job execution | Runner queue per job |
| --- | --- | --- | --- | --- |
| CI | [35048795873](https://github.com/michel-tricot/airmux/actions/runs/35048795873) | 590 s | Backend 297 s | 3 to 117 s |
| Docker | [35048795869](https://github.com/michel-tricot/airmux/actions/runs/35048795869) | 452 s | Split deployment 174 s | 2 to 111 s |
| Security | [35048795731](https://github.com/michel-tricot/airmux/actions/runs/35048795731) | 215 s | Python audit 15 s | 44 to 196 s |

Docker execution was similar to baseline (174 s versus 169 s); its classifier executed for 18 s and aggregate for 14 s. The Python audit executed for 15 s versus 19 s before, but queued for 196 s versus 3 s. Higher elapsed times in this sample are dominated by runner queues and waiting for obsolete workflow cancellation. No five-minute elapsed-time claim or measured docs-only speedup follows from this full-validation sample.

CI's longest execution was 297 s versus 282 s before; full-stack acceptance took 293 s versus 243 s, frontend 200 s versus 144 s, and performance comparison 214 s versus 218 s. The classifier executed for 18 s, documentation/workflow checks for 19 s, and the final aggregate for 16 s. The CI workflow waited 167 s for the prior revision to finish cancellation before its initial jobs were created. Every validation job and both aggregate gates passed in this sample. The measurements keep the five-minute execution target plausible, but do not demonstrate an elapsed-time improvement under these queue conditions.

Fetch job timestamps with `gh api repos/michel-tricot/airmux/actions/runs/RUN_ID/jobs --paginate`. Compare full-validation runs separately from docs-only or frontend-only runs, and record cancelled predecessors separately from completed revisions.
