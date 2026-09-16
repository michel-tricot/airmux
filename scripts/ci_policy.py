from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import typer
from pydantic import BaseModel, ConfigDict, RootModel

Scope = Literal["ci", "docker", "gateway"]
Result = Literal["success", "failure", "cancelled", "skipped"]
Flag = Literal["true", "false"]

app = typer.Typer()


@dataclass(frozen=True)
class Selection:
    frontend: bool = True
    backend: bool = True
    deployment: bool = True

    def __post_init__(self) -> None:
        if (self.frontend, self.backend, self.deployment) not in {(False, False, False), (True, False, True), (True, True, True)}:
            message = "Change policy must select documentation, frontend with Docker, or full validation"
            raise ValueError(message)


def classify(paths: tuple[str, ...], event: str) -> Selection:
    if event != "pull_request" or not paths:
        return Selection()
    documentation = ("docs/", "notes/")
    frontend = ("apps/console/", "lib/api-client-react/")
    if any(
        path.endswith(("/package.json", "/pyproject.toml", ".lock"))
        or not (path.startswith((*documentation, *frontend)) or path in {"README.md", "CONTRIBUTING.md", "docs.json"})
        for path in paths
    ):
        return Selection()
    has_frontend = any(path.startswith(frontend) for path in paths)
    return Selection(frontend=has_frontend, backend=False, deployment=has_frontend)


def changed_paths(base: str, head: str, root: Path = Path()) -> tuple[str, ...]:
    if not all(re.fullmatch(r"[0-9a-f]{40}", revision) for revision in (base, head)):
        message = "Change classification requires full base and head commit SHAs"
        raise ValueError(message)
    diff = subprocess.run(  # noqa: S603 commit SHAs are validated and git receives a fixed argument list
        ["/usr/bin/git", "diff", "--no-renames", "--name-only", "-z", f"{base}...{head}", "--"],
        cwd=root,
        capture_output=True,
        check=True,
    )
    return tuple(path for path in diff.stdout.decode().split("\0") if path)


def required_jobs(selection: Selection, scope: Scope) -> dict[str, bool]:
    gateway = {"installation-smoke": selection.backend, "installation": selection.backend, "gateway-acceptance": selection.backend}
    if scope == "gateway":
        return gateway
    if scope == "docker":
        return {"deployment": selection.deployment}
    return {
        "workflows": True,
        "frontend": selection.frontend,
        "backend": selection.backend,
        "python-distributions": selection.backend,
        "installation-smoke": selection.backend,
        **gateway,
        "gateway-results": selection.backend,
        "acceptance": selection.backend,
        "browser-acceptance": selection.frontend,
    }


class Job(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    result: Result
    outputs: dict[str, str]


class Outputs(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    frontend: Flag
    backend: Flag
    deployment: Flag


def validate_results(needs: str, scope: Scope) -> None:
    jobs = RootModel[dict[str, Job]].model_validate_json(needs).root
    changes = jobs.get("changes")
    if changes is None or changes.result != "success":
        message = "changes must succeed before required checks can pass"
        raise ValueError(message)
    outputs = Outputs.model_validate(changes.outputs)
    selection = Selection(outputs.frontend == "true", outputs.backend == "true", outputs.deployment == "true")
    expected = required_jobs(selection, scope)
    if set(jobs) != {"changes", *expected}:
        message = "Aggregate dependencies must match the required check policy"
        raise ValueError(message)
    unsuccessful = [name for name, required in expected.items() if jobs[name].result != "success" and (required or jobs[name].result != "skipped")]
    if unsuccessful:
        message = f"Required check results rejected: {', '.join(unsuccessful)}"
        raise ValueError(message)


@app.command("classify")
def classify_command(event: str, base: str = "", head: str = "") -> None:
    paths = changed_paths(base, head) if event == "pull_request" else ()
    selection = classify(paths, event)
    with Path(os.environ["GITHUB_OUTPUT"]).open("a") as output:
        output.write("".join(f"{name}={str(value).lower()}\n" for name, value in vars(selection).items()))
    with Path(os.environ["GITHUB_STEP_SUMMARY"]).open("a") as summary:
        summary.write("| Check family | Selected |\n| --- | --- |\n")
        summary.write("".join(f"| {name} | {value} |\n" for name, value in vars(selection).items()))


@app.command("gate")
def gate_command(scope: Scope) -> None:
    validate_results(os.environ["NEEDS"], scope)


if __name__ == "__main__":
    app()
