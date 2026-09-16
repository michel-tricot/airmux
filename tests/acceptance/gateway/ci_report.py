from __future__ import annotations

import html
import os
import platform
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Annotated

import typer

app = typer.Typer()
MAX_FAILURES = 50
MAX_DETAIL_CHARS = 10000


def annotation(message: str) -> str:
    return message.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


@app.command()
def report(directory: Path, summary: Annotated[Path, typer.Option()]) -> None:
    reports = sorted(directory.rglob("*.xml"))
    sections = ["## Evidence", "", f"Commit: `{os.environ.get('GITHUB_SHA', 'local')}`", f"Python: `{platform.python_version()}`"]
    digests = Path("candidate/SHA256SUMS")
    if digests.is_file():
        sections.extend(["", "Candidate SHA-256:", "", "```text", digests.read_text().strip(), "```"])
    sections.extend(["", "## Test results", "", "| Suite / level | Tests | Failures | Errors | Skipped |", "| --- | ---: | ---: | ---: | ---: |"])
    failures: list[tuple[str, str, str]] = []
    for path in reports:
        root = ET.parse(path).getroot()  # noqa: S314 reports are generated locally by pytest
        suites = [root] if root.tag == "testsuite" else list(root.iter("testsuite"))
        counts = [sum(int(suite.get(field, "0")) for suite in suites) for field in ("tests", "failures", "errors", "skipped")]
        sections.append(f"| {html.escape(path.stem)} | " + " | ".join(str(count) for count in counts) + " |")
        failures.extend(
            (
                f"{case.get('classname', '')}::{case.get('name', 'collection')}",
                failure.get("message", failure.tag),
                failure.text or failure.get("message", failure.tag),
            )
            for case in root.iter("testcase")
            for failure in case
            if failure.tag in {"failure", "error"}
        )
    if not reports:
        sections.extend(["", "No test reports were produced. Check the setup and test runner logs."])
    for index, (name, message, detail) in enumerate(failures[:MAX_FAILURES]):
        sections.extend(
            ["", f"<details><summary>{html.escape(name)}</summary>", "", f"<pre>{html.escape(detail)[:MAX_DETAIL_CHARS]}</pre>", "", "</details>"]
        )
        if index < 10:
            typer.echo(f"::error::{annotation(name + ': ' + message)}")
    if len(failures) > MAX_FAILURES:
        sections.extend(["", f"Showing the first {MAX_FAILURES} failures."])
    sections.extend(
        [
            "",
            "Full tracebacks are in the test step logs. Download the job's test-results artifact for the JUnit reports.",
            "",
        ]
    )
    with summary.open("a", encoding="utf-8") as output:
        output.write("\n".join(sections))


if __name__ == "__main__":
    app()
