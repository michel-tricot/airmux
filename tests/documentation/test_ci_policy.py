from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
import yaml
from scripts.ci_policy import Scope, Selection, app, changed_paths, classify, required_jobs, validate_results
from typer.testing import CliRunner

ROOT = Path(__file__).parents[2]


@pytest.mark.parametrize(
    ("paths", "expected"),
    [
        (("docs/development.mdx",), Selection(frontend=False, backend=False, deployment=False)),
        (("README.md", "notes/design/POLICIES.md", "docs.json"), Selection(frontend=False, backend=False, deployment=False)),
        (("apps/console/src/App.tsx",), Selection(frontend=True, backend=False, deployment=True)),
        (("lib/api-client-react/src/generated/api.ts",), Selection(frontend=True, backend=False, deployment=True)),
        (("apps/control-plane/src/control_plane/app.py",), Selection()),
        (("apps/data-plane/src/data_plane/app.py",), Selection()),
        (("lib/api-spec/openapi.yaml",), Selection()),
        (("lib/contract/src/contract/bundle.py",), Selection()),
        (("packaging/airmux/pyproject.toml",), Selection()),
        (("bun.lock",), Selection()),
        (("uv.lock",), Selection()),
        (("apps/console/package.json",), Selection()),
        (("scripts/build-python-distribution.sh",), Selection()),
        ((".github/workflows/ci.yml",), Selection()),
        (("Dockerfile",), Selection()),
        (("tests/pg.py",), Selection()),
        (("new-directory/new-file.txt",), Selection()),
        (("docs/development.mdx", "lib/contract/src/contract/bundle.py"), Selection()),
        ((), Selection()),
    ],
)
def test_changed_paths_select_checks(paths, expected):
    assert classify(paths, "pull_request") == expected


@pytest.mark.parametrize("event", ["push", "workflow_dispatch", "release", "workflow_call"])
def test_non_pr_events_always_select_full_validation(event):
    assert classify(("docs/development.mdx",), event) == Selection()


@pytest.mark.parametrize("flags", [(False, True, True), (True, True, False), (True, False, False)])
def test_aggregate_rejects_inconsistent_classifier_outputs(flags):
    results = job_results(Selection())
    results["changes"]["outputs"] = {name: str(value).lower() for name, value in zip(("frontend", "backend", "deployment"), flags, strict=True)}
    with pytest.raises(ValueError, match="Change policy must select"):
        validate_results(json.dumps(results), "ci")


def job_results(selection, scope="ci"):
    return {
        "changes": {"result": "success", "outputs": {name: str(value).lower() for name, value in vars(selection).items()}},
        **{name: {"result": "success" if required else "skipped", "outputs": {}} for name, required in required_jobs(selection, scope).items()},
    }


@pytest.mark.parametrize("selection", [Selection(), Selection(False, False, False), Selection(True, False, True)])
@pytest.mark.parametrize("scope", ["ci", "docker", "gateway"])
def test_aggregate_accepts_only_policy_permitted_skips(selection, scope):
    validate_results(json.dumps(job_results(selection, scope)), scope)


@pytest.mark.parametrize("result", ["failure", "cancelled", "skipped"])
@pytest.mark.parametrize("scope", ["ci", "docker", "gateway"])
def test_aggregate_rejects_unsuccessful_required_work(result, scope):
    results = job_results(Selection(), scope)
    name = next(iter(required_jobs(Selection(), scope)))
    results[name]["result"] = result
    with pytest.raises(ValueError, match=name):
        validate_results(json.dumps(results), scope)


@pytest.mark.parametrize("result", ["failure", "cancelled", "skipped"])
def test_aggregate_rejects_classifier_failure(result):
    results = job_results(Selection(False, False, False))
    results["changes"]["result"] = result
    with pytest.raises(ValueError, match="changes"):
        validate_results(json.dumps(results), "ci")


@pytest.mark.parametrize("mutation", ["missing-job", "missing-output", "invalid-output", "failed-optional", "cancelled-optional", "malformed"])
def test_aggregate_fails_closed(mutation):
    results = job_results(Selection(False, False, False))
    match mutation:
        case "missing-job":
            del results["backend"]
        case "missing-output":
            del results["changes"]["outputs"]["backend"]
        case "invalid-output":
            results["changes"]["outputs"]["backend"] = "maybe"
        case "failed-optional":
            results["backend"]["result"] = "failure"
        case "cancelled-optional":
            results["backend"]["result"] = "cancelled"
        case "malformed":
            results = {"unexpected": True}
    with pytest.raises(ValueError, match=r"dependencies|validation error|results rejected"):
        validate_results(json.dumps(results), "ci")


def test_classifier_reads_deletions_and_renames_without_truncating(tmp_path):
    def git(*arguments):
        return subprocess.run(  # noqa: S603 arguments are fixed by this test and operate on its temporary repository
            ["/usr/bin/git", "-C", str(tmp_path), *arguments], check=True, capture_output=True, text=True
        ).stdout.strip()

    git("init", "-b", "main")
    git("config", "user.email", "ci@example.com")
    git("config", "user.name", "CI")
    (tmp_path / "backend.py").write_text("backend\n")
    git("add", ".")
    git("commit", "-m", "base")
    base = git("rev-parse", "HEAD")
    git("mv", "backend.py", "README.md")
    for index in range(3100):
        (tmp_path / f"doc-{index}.md").write_text("docs\n")
    git("add", ".")
    git("commit", "-m", "candidate")
    paths = changed_paths(base, git("rev-parse", "HEAD"), tmp_path)
    assert len(paths) == 3102
    assert "backend.py" in paths
    assert classify(paths, "pull_request") == Selection()
    with pytest.raises(ValueError, match="full base and head commit SHAs"):
        changed_paths("missing", git("rev-parse", "HEAD"), tmp_path)
    with pytest.raises(subprocess.CalledProcessError):
        changed_paths("0" * 40, git("rev-parse", "HEAD"), tmp_path)


def test_policy_cli_emits_outputs_and_returns_failure_for_invalid_dependencies(tmp_path):
    output = tmp_path / "outputs"
    summary = tmp_path / "summary"
    runner = CliRunner()
    result = runner.invoke(app, ["classify", "workflow_dispatch"], env={"GITHUB_OUTPUT": str(output), "GITHUB_STEP_SUMMARY": str(summary)})
    assert result.exit_code == 0, result.output
    assert output.read_text() == "frontend=true\nbackend=true\ndeployment=true\n"
    assert "| frontend | True |" in summary.read_text()
    results = job_results(Selection(False, False, False))
    assert runner.invoke(app, ["gate", "ci"], env={"NEEDS": json.dumps(results)}).exit_code == 0
    results["gateway-performance"]["result"] = "cancelled"
    assert runner.invoke(app, ["gate", "ci"], env={"NEEDS": json.dumps(results)}).exit_code != 0


def test_every_workflow_is_parsable_and_filters_jobs_instead_of_triggers():
    for path in (ROOT / ".github/workflows").glob("*.yml"):
        workflow = yaml.safe_load(path.read_text())
        triggers = workflow.get("on", workflow.get(True))
        for event in ("pull_request", "push"):
            assert "paths" not in (triggers.get(event) or {})
            assert "paths-ignore" not in (triggers.get(event) or {})


def test_workflow_aggregates_cover_all_validation_jobs():
    workflows: list[tuple[str, Scope, str]] = [("ci.yml", "ci", "ci"), ("docker-deployments.yml", "docker", "deployment-results")]
    for filename, scope, aggregate in workflows:
        jobs = yaml.safe_load((ROOT / ".github/workflows" / filename).read_text())["jobs"]
        expected = {"changes", *required_jobs(Selection(), scope)}
        assert set(jobs[aggregate]["needs"]) == expected
        assert set(jobs) == expected | {aggregate}
        assert jobs[aggregate]["if"] == "always()"
        for name, required in required_jobs(Selection(False, False, False), scope).items():
            if not required:
                assert "needs.changes.outputs." in jobs[name]["if"]


def test_security_cancellation_is_pr_only_and_non_pr_groups_are_unique():
    workflow = yaml.safe_load((ROOT / ".github/workflows/dependency-security.yml").read_text())
    assert workflow["concurrency"]["cancel-in-progress"] == "${{ github.event_name == 'pull_request' }}"
    group = workflow["concurrency"]["group"]
    assert "github.workflow" in group
    assert "github.event.pull_request.number" in group
    assert "github.run_id" in group
