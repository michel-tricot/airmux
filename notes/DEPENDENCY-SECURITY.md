# Dependency security scans

The dependency-security workflow runs on pull requests, pushes to main, weekly, and manually. Four independent scans cover all Python workspace dependencies, production backend dependencies, all JavaScript dependencies, and production JavaScript dependencies. Scans use the committed lockfiles without upgrading packages.

Vulnerability findings are informational while they are triaged. Scanner failures, skipped Python dependencies, malformed reports, and inconsistent exit statuses fail the job so an incomplete scan cannot appear clean. JSON reports, scanner diagnostics, and readable summaries are retained for 30 days and tied to the tested commit. The workflow does not create upgrade commits or post comments.

Python production scope is the `backend` dependency group used for the gateway runtime. JavaScript production scope is Bun's `--prod` dependency classification, which is not proof of browser-bundle reachability. Compare all-dependency reports with production reports before deciding whether a finding concerns runtime code, developer tools, or build infrastructure. Package advisories describe affected versions; exploitability requires examining how AirLLM uses the package.

The Python scanner is pinned to pip-audit 2.10.0; JavaScript uses the CI Bun version, 1.3.14. The advisory databases are queried on each scan, so unchanged lockfiles can produce new findings. Repository package dependencies are not modified by the workflow.

Container operating-system scans and release provenance are deferred until artifacts are published.
