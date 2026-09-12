from __future__ import annotations

import html
import json
from enum import StrEnum
from pathlib import Path
from typing import Annotated

import typer
from pydantic import BaseModel, Field, TypeAdapter

app = typer.Typer()


class Ecosystem(StrEnum):
    python = "python"
    javascript = "javascript"


class AuditScope(StrEnum):
    all = "all"
    production = "production"


class PythonVulnerability(BaseModel):
    id: str
    fix_versions: list[str]


class PythonDependency(BaseModel):
    name: str
    version: str
    vulns: list[PythonVulnerability]


class PythonAudit(BaseModel):
    dependencies: list[PythonDependency] = Field(min_length=1)


class JavascriptVulnerability(BaseModel):
    id: int
    url: str
    severity: str
    vulnerable_versions: str


def summarize(ecosystem: Ecosystem, report: str, status: int, scope: AuditScope) -> str:
    if status not in {0, 1}:
        message = f"Scanner failed with exit status {status}"
        raise ValueError(message)
    if ecosystem == "python":
        audit = PythonAudit.model_validate_json(report)
        findings = [
            f"{dependency.name} {dependency.version}: {vulnerability.id}; fixes: {', '.join(vulnerability.fix_versions) or 'none published'}"
            for dependency in audit.dependencies
            for vulnerability in dependency.vulns
        ]
    elif ecosystem == "javascript":
        advisories = TypeAdapter(dict[str, list[JavascriptVulnerability]]).validate_json(report)
        findings = [
            f"{package}: {advisory.url}; severity: {advisory.severity}; affected: {advisory.vulnerable_versions}"
            for package, vulnerabilities in advisories.items()
            for advisory in vulnerabilities
        ]
    else:
        message = f"Unsupported ecosystem: {ecosystem}"
        raise ValueError(message)
    if bool(findings) != bool(status):
        message = "Scanner exit status does not match its report"
        raise ValueError(message)
    details = html.escape("\n".join(findings))
    return (
        f"### {html.escape(ecosystem)} / {html.escape(scope)}\n\n"
        f"{len(findings)} advisory occurrences. Findings are informational pending triage.\n\n"
        f"<pre>{details or 'No known advisories reported'}</pre>\n"
    )


@app.command()
def report(
    ecosystem: Annotated[Ecosystem, typer.Option()],
    source: Annotated[Path, typer.Option(exists=True)],
    status_file: Annotated[Path, typer.Option(exists=True)],
    scope: Annotated[AuditScope, typer.Option()],
    summary: Annotated[Path, typer.Option()] = Path("security-reports/summary.md"),
) -> None:
    try:
        rendered = summarize(ecosystem, source.read_text(), int(status_file.read_text().strip()), scope)
    except (ValueError, OSError, json.JSONDecodeError) as error:
        typer.echo(f"Dependency scan incomplete: {error}", err=True)
        raise typer.Exit(1) from error
    summary.write_text(rendered)
    typer.echo(f"Wrote dependency summary to {summary}")


if __name__ == "__main__":
    app()
