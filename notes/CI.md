# CI topology and evidence

`ci.yml` runs the same correctness graph for every pull request and every main commit. It has no semantic path map,
path trigger, or conditional correctness skip. `quality`, `python-unit`, `python-integration`, `frontend`, and
`package` begin independently. The package job builds the source distribution once, rebuilds the wheel from it, and
records SHA-256 digests. Gateway, full-stack, browser, and Docker jobs consume that wheel. The stable `required` job
uses only runner `jq` and succeeds only when every correctness job succeeds.

`security.yml` runs dependency audits on pull requests, main, and weekly. Its stable `dependency-security` aggregate
requires both ecosystem audits and dependency review when the event supports it. Repository CodeQL default setup,
secret scanning, action restrictions, branch protection, tag protection, and the release environment are recorded in
`.github/policy`. `scripts/github-policy diff` reads live settings without mutation; `apply` is the explicit write path.

`nightly.yml` owns Python 3.13/3.14 Linux/macOS compatibility, repeated gateway performance, real providers, longer
concurrency runs, and a cold Docker build. Manual runs accept a full SHA and reject commits outside main. Benchmark
evidence is retained for 90 days. These jobs never receive untrusted pull-request code.

`release.yml` accepts only a protected version tag, derives its SHA, requires successful `required` and
`dependency-security` jobs for that exact main commit, then downloads the sdist-derived main-CI candidate. Installation,
real-provider, PyPI publishing, registry hash comparison, isolated installation, and the final gateway request all use
those bytes. GitHub release publication happens last.

Track pull-request required-check p50 and p95, queue p95, infrastructure failure rate, main green rate, retries, and
missing-test incidents weekly. Targets are p50 under four minutes, p95 under six minutes, queue p95 under one minute,
infrastructure failures below 0.5%, main green rate above 99%, and zero retries or missing-test incidents. Record
exceptions here after enough runs exist to make the percentiles meaningful.
