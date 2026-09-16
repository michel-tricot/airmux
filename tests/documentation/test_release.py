from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).parents[2]
PUBLISH = yaml.safe_load((ROOT / ".github/workflows/publish.yml").read_text())
WORKFLOWS = ("ci.yml", "docker-deployments.yml", "dependency-security.yml")
SHA = "a" * 40


def executable(name: str) -> str:
    executable_path = shutil.which(name)
    assert executable_path is not None
    return executable_path


NODE = executable("node")
GIT = executable("git")
BASH = executable("bash")


def validation_step(name):
    return next(step for step in PUBLISH["jobs"]["build"]["steps"] if step.get("name") == name)


@pytest.mark.parametrize(
    "override",
    [
        {},
        {"status": "queued", "conclusion": None},
        {"status": "in_progress", "conclusion": None},
        {"conclusion": "failure"},
        {"conclusion": "cancelled"},
        {"conclusion": "skipped"},
        {"head_sha": "b" * 40},
        {"event": "pull_request"},
        {"head_branch": "contributor"},
        {"head_repository": {"full_name": "contributor/airmux"}},
        {"workflow_id": 999},
        {"path": ".github/workflows/untrusted.yml"},
        {"absent": True},
        {"api_error": True},
        {"inactive": True},
        {"untrusted_definition": True},
    ],
)
@pytest.mark.parametrize("workflow", WORKFLOWS)
def test_release_requires_latest_successful_trusted_exact_commit_run(workflow, override):
    script = validation_step("Verify exact-commit CI")["with"]["script"]
    runner = """
const fixture = JSON.parse(process.argv[1]);
const workflows = ['ci.yml', 'docker-deployments.yml', 'dependency-security.yml'];
const context = {repo: {owner: 'michel-tricot', repo: 'airmux'}};
const github = {rest: {actions: {
  getWorkflow: async ({workflow_id}) => ({data: {
    id: workflows.indexOf(workflow_id) + 1,
    path: fixture.override.untrusted_definition && workflow_id === fixture.workflow
      ? '.github/workflows/untrusted.yml' : `.github/workflows/${workflow_id}`,
    state: fixture.override.inactive && workflow_id === fixture.workflow ? 'disabled_manually' : 'active'
  }}),
  listWorkflowRuns: async ({workflow_id, branch, event, head_sha, per_page}) => {
    const filename = workflows[workflow_id - 1];
    const success = {
      workflow_id, path: `.github/workflows/${filename}`, head_branch: branch, event, head_sha,
      head_repository: {full_name: 'michel-tricot/airmux'}, status: 'completed', conclusion: 'success',
      html_url: `https://github.com/michel-tricot/airmux/actions/runs/${workflow_id}`
    };
    const override = filename === fixture.workflow ? fixture.override : {};
    if (override.api_error) throw new Error('API unavailable');
    return {data: {workflow_runs: override.absent ? [] : [{...success, ...override}, success].slice(0, per_page)}};
  }
}}};
const core = {info: () => {}};
const AsyncFunction = Object.getPrototypeOf(async function(){}).constructor;
new AsyncFunction('github', 'context', 'core', fixture.script)(github, context, core)
  .then(() => process.stdout.write('allowed'))
  .catch(() => process.stdout.write('blocked'));
"""
    result = subprocess.run(  # noqa: S603 executes the checked-in workflow with synthetic API responses
        [NODE, "-e", runner, json.dumps({"script": script, "workflow": workflow, "override": override})],
        env={**os.environ, "RELEASE_SHA": SHA},
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout == ("blocked" if override else "allowed")


@pytest.mark.parametrize("failure", [None, "moved", "version", "ancestry"])
def test_release_source_validation_pins_the_event_commit(tmp_path, failure):
    def git(*arguments):
        return subprocess.run([GIT, *arguments], cwd=tmp_path, capture_output=True, text=True, check=True).stdout.strip()  # noqa: S603 fixed test git arguments

    git("init", "-b", "main")
    git("config", "user.email", "release@example.com")
    git("config", "user.name", "Release test")
    package = tmp_path / "packaging/airmux"
    package.mkdir(parents=True)
    (package / "pyproject.toml").write_text('[project]\nname = "airmux"\nversion = "0.1.0"\n')
    git("add", ".")
    git("commit", "-m", "Release")
    sha = git("rev-parse", "HEAD")
    git("branch", "origin/main")
    if failure == "ancestry":
        git("checkout", "-b", "untrusted")
        git("commit", "--allow-empty", "-m", "Unmerged")
        sha = git("rev-parse", "HEAD")
    tag = "v0.2.0" if failure == "version" else "v0.1.0"
    git("tag", "-a", tag, "-m", "Release")
    output = tmp_path / "output"
    result = subprocess.run(  # noqa: S603 executes the checked-in source check in a disposable repository
        [BASH, "-e", "-o", "pipefail", "-c", validation_step("Verify release source and version")["run"]],
        cwd=tmp_path,
        env={
            **os.environ,
            "RELEASE_TAG": tag,
            "RELEASE_SHA": "b" * 40 if failure == "moved" else sha,
            "GITHUB_OUTPUT": str(output),
            "UV_CACHE_DIR": str(tmp_path / "uv-cache"),
        },
        capture_output=True,
        text=True,
        check=False,
    )
    assert (result.returncode == 0) == (failure is None)
    if failure is None:
        assert output.read_text() == f"sha={sha}\nversion=0.1.0\n"


def test_release_jobs_share_the_validated_sha_and_artifact():
    jobs = PUBLISH["jobs"]
    checkout = next(step for step in jobs["build"]["steps"] if step.get("uses", "").startswith("actions/checkout@"))
    assert checkout["with"]["ref"] == "${{ inputs.sha }}"
    assert jobs["live-providers"]["with"]["ref"] == "${{ needs.build.outputs.sha }}"
    assert jobs["live-providers"]["needs"] == "build"
    artifact = "${{ needs.build.outputs.artifact-id }}"
    assert jobs["live-providers"]["with"]["distribution-artifact-id"] == artifact
    download = next(step for step in jobs["publish"]["steps"] if step.get("uses", "").startswith("actions/download-artifact@"))
    assert download["with"]["artifact-ids"] == artifact
    verify_download = next(step for step in jobs["verify-pypi"]["steps"] if step.get("uses", "").startswith("actions/download-artifact@"))
    assert verify_download["with"]["artifact-ids"] == artifact
    assert set(jobs["publish"]["needs"]) == {"build", "live-providers"}
    assert PUBLISH["concurrency"] == {"group": "publish-${{ inputs.tag }}", "cancel-in-progress": False}
    assert jobs["build"]["permissions"] == {"contents": "read", "actions": "read"}
    assert jobs["live-providers"]["permissions"] == {"contents": "read"}
    assert jobs["publish"]["permissions"] == {"contents": "read", "id-token": "write"}


def test_release_source_policy_preserves_daily_checks_and_immutable_tags():
    policy = ROOT / ".github/release-policy"
    creation = json.loads((policy / "tag-creation.json").read_text())
    immutable = json.loads((policy / "tag-immutability.json").read_text())
    for ruleset in (creation, immutable):
        assert ruleset["target"] == "tag"
        assert ruleset["enforcement"] == "active"
        assert ruleset["conditions"]["ref_name"] == {"include": ["refs/tags/v*"], "exclude": []}
    assert creation["rules"] == [{"type": "creation"}]
    assert creation["bypass_actors"] == [{"actor_id": 5, "actor_type": "RepositoryRole", "bypass_mode": "always"}]
    assert immutable["rules"] == [{"type": "update"}, {"type": "deletion"}]
    assert immutable["bypass_actors"] == []
    environment = json.loads((policy / "environment.json").read_text())
    assert environment["can_admins_bypass"] is False
    assert environment["deployment_branch_policy"] == {"protected_branches": False, "custom_branch_policies": True}
    sources = json.loads((policy / "sources.json").read_text())
    assert sources == [{"name": "v*", "type": "tag"}, {"name": "main", "type": "branch"}]
    providers = yaml.safe_load((ROOT / ".github/workflows/live-providers.yml").read_text())
    assert providers["jobs"]["acceptance"]["environment"] == "release"
