from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Literal

import typer
from dotenv import load_dotenv

from provider_parity.cases import load_cases, load_expected_differences
from provider_parity.catalog import load_catalog
from provider_parity.diagnostics import case_result
from provider_parity.drivers import supported_endpoints
from provider_parity.gateway import Gateway
from provider_parity.models import Plan, ReportDocument
from provider_parity.output import Col, FormatOption, OutputFormat, print_rows
from provider_parity.plan import Filters, build_plan
from provider_parity.progress import ConsoleProgress
from provider_parity.provenance import metadata
from provider_parity.report import write_report
from provider_parity.runner import ExecutionOptions, execute

ROOT = Path(__file__).resolve().parents[3]
CASES = ROOT / "provider-parity" / "cases"
DIFFERENCES = ROOT / "provider-parity" / "expected-differences.yml"
REPORTS = ROOT / "provider-parity" / "reports"

ProviderOption = Annotated[str | None, typer.Option("--provider")]
ModelOption = Annotated[str | None, typer.Option("--model")]
CaseOption = Annotated[str | None, typer.Option("--case")]
SDKOption = Annotated[str | None, typer.Option("--sdk")]
SurfaceOption = Annotated[str | None, typer.Option("--surface")]
TransportOption = Annotated[Literal["buffered", "streamed"] | None, typer.Option("--transport")]
UnknownOption = Annotated[bool, typer.Option("--include-unknown", help="Include parameters whose support is not known")]
GatewayUrlOption = Annotated[str | None, typer.Option("--gateway-url", help="Origin of the running AirLLM data plane")]
GatewayKeyOption = Annotated[str | None, typer.Option("--gateway-api-key", help="Inference key accepted by the running data plane")]

app = typer.Typer(name="airllm-parity", no_args_is_help=True)
cases_app = typer.Typer(name="cases", no_args_is_help=True)
targets_app = typer.Typer(name="targets", no_args_is_help=True)
runs_app = typer.Typer(name="runs", no_args_is_help=True)
reports_app = typer.Typer(name="reports", no_args_is_help=True)
app.add_typer(cases_app)
app.add_typer(targets_app)
app.add_typer(runs_app)
app.add_typer(reports_app)


def _plan(filters: Filters) -> Plan:
    catalog = load_catalog(ROOT / "taxonomy")
    return build_plan(catalog.targets, load_cases(CASES), supported_endpoints(), filters)


@cases_app.command("list")
def cases_list(output_format: FormatOption = OutputFormat.table) -> None:
    rows = [
        {
            "id": case.id,
            "title": case.title,
            "requires": ", ".join(sorted(case.requires.capabilities | case.requires.parameters | case.requires.input_modalities)),
            "transports": ", ".join(case.transports),
        }
        for case in load_cases(CASES)
    ]
    print_rows("cases", rows, [Col("id", "Case"), Col("title", "Title"), Col("requires", "Requires"), Col("transports", "Transports")], output_format)


@targets_app.command("list")
def targets_list(
    provider: ProviderOption = None, model: ModelOption = None, surface: SurfaceOption = None, output_format: FormatOption = OutputFormat.table
) -> None:
    targets = load_catalog(ROOT / "taxonomy").targets
    rows = [
        {
            "provider": target.provider_id,
            "surface": target.surface_id,
            "model": target.model_id,
            "endpoint": target.endpoint,
            "capabilities": ", ".join(sorted(target.capabilities)),
        }
        for target in targets
        if (provider is None or target.provider_id == provider)
        and (model is None or target.model_id == model)
        and (surface is None or target.surface_id == surface)
    ]
    print_rows(
        "targets",
        rows,
        [
            Col("provider", "Provider"),
            Col("surface", "Surface"),
            Col("model", "Model"),
            Col("endpoint", "Endpoint"),
            Col("capabilities", "Capabilities"),
        ],
        output_format,
    )


@runs_app.command("plan")
def runs_plan(  # noqa: PLR0913, PLR0917 command flags define the CLI surface
    provider: ProviderOption = None,
    model: ModelOption = None,
    case: CaseOption = None,
    sdk: SDKOption = None,
    surface: SurfaceOption = None,
    transport: TransportOption = None,
    include_unknown: UnknownOption = False,
    output_format: FormatOption = OutputFormat.table,
) -> None:
    plan = _plan(
        Filters(
            provider=provider,
            model=model,
            case=case,
            sdk=sdk,
            surface=surface,
            transport=transport,
            include_unknown=include_unknown,
        )
    )
    rows = [
        {
            "provider": experiment.target.provider_id,
            "surface": experiment.target.surface_id,
            "model": experiment.target.model_id,
            "sdk": experiment.driver_id,
            "case": experiment.case.id,
            "transport": experiment.transport,
        }
        for experiment in plan.experiments
    ]
    print_rows(
        "experiments",
        rows,
        [
            Col("provider", "Provider"),
            Col("surface", "Surface"),
            Col("model", "Model"),
            Col("sdk", "SDK"),
            Col("case", "Case"),
            Col("transport", "Transport"),
        ],
        output_format,
    )
    typer.echo(f"{len(plan.experiments)} paired experiments, {plan.requests} requests, {plan.skipped} unsupported combinations skipped", err=True)


@runs_app.command("execute")
def runs_execute(  # noqa: PLR0913, PLR0917 command flags define the CLI surface
    provider: ProviderOption = None,
    model: ModelOption = None,
    case: CaseOption = None,
    sdk: SDKOption = None,
    surface: SurfaceOption = None,
    transport: TransportOption = None,
    include_unknown: UnknownOption = False,
    gateway_url: GatewayUrlOption = None,
    gateway_api_key: GatewayKeyOption = None,
    yes: Annotated[bool, typer.Option("--yes", help="Confirm a run above the request guardrail")] = False,
    max_requests: Annotated[int, typer.Option("--max-requests", min=1)] = 500,
    confirmations: Annotated[int, typer.Option("--confirmations", min=0, max=5, help="Paired reruns for a suspected difference")] = 1,
    request_timeout: Annotated[float, typer.Option("--request-timeout", min=0.1, help="Per-request timeout in seconds")] = 60,
    output_format: FormatOption = OutputFormat.table,
) -> None:
    load_dotenv(ROOT / ".env")
    gateway_url = gateway_url or os.environ.get("AIRLLM_GATEWAY_URL")
    gateway_api_key = gateway_api_key or os.environ.get("AIRLLM_API_KEY")
    if gateway_url is None:
        message = "set AIRLLM_GATEWAY_URL or pass --gateway-url"
        raise typer.BadParameter(message)
    if gateway_api_key is None:
        message = "set AIRLLM_API_KEY or pass --gateway-api-key"
        raise typer.BadParameter(message)
    plan = _plan(
        Filters(
            provider=provider,
            model=model,
            case=case,
            sdk=sdk,
            surface=surface,
            transport=transport,
            include_unknown=include_unknown,
        )
    )
    if not plan.experiments:
        message = "the selected run has no applicable experiments"
        raise typer.BadParameter(message)
    maximum_requests = plan.requests * (confirmations + 1)
    if maximum_requests > max_requests and not yes:
        message = f"the run can schedule up to {maximum_requests} requests including confirmations; pass --yes or narrow the selection"
        raise typer.BadParameter(message)
    gateway = Gateway(base_url=gateway_url, api_key=gateway_api_key, request_timeout_seconds=request_timeout)
    progress = ConsoleProgress()
    progress.start(plan, gateway.base_url, confirmations)
    results = execute(
        plan,
        gateway,
        load_expected_differences(DIFFERENCES),
        progress=progress,
        options=ExecutionOptions(confirmations=confirmations, request_timeout_seconds=request_timeout),
    )
    run_id = datetime.now(tz=UTC).strftime("%Y%m%dT%H%M%SZ")
    paths = write_report(results, REPORTS, run_id, metadata(ROOT, run_id, gateway.base_url))
    rows = [
        {
            "provider": result.provider_id,
            "surface": result.surface_id,
            "model": result.model_id,
            "case": result.case_id,
            "verdict": result.comparison.verdict,
            "case_result": case_result(result.comparison),
            "differences": ", ".join(result.comparison.differences),
            "attempts": len(result.confirmations) + 1,
        }
        for result in results
    ]
    print_rows(
        "results",
        rows,
        [
            Col("provider", "Provider"),
            Col("surface", "Surface"),
            Col("model", "Model"),
            Col("case", "Case"),
            Col("verdict", "Verdict"),
            Col("case_result", "Case result"),
            Col("differences", "Differences"),
            Col("attempts", "Attempts"),
        ],
        output_format,
    )
    typer.echo(f"wrote {paths.json_path} and {paths.html_path}", err=True)
    if any(result.comparison.verdict in {"gateway_regression", "different"} for result in results):
        raise typer.Exit(1)


@reports_app.command("show")
def reports_show(path: Path | None = None, output_format: FormatOption = OutputFormat.table) -> None:
    candidates = sorted(REPORTS.glob("*.json"))
    selected = path or (candidates[-1] if candidates else None)
    if selected is None:
        message = "no parity report exists"
        raise typer.BadParameter(message)
    results = ReportDocument.model_validate(json.loads(selected.read_text(encoding="utf-8"))).results
    rows = [
        {
            "provider": result.provider_id,
            "surface": result.surface_id,
            "model": result.model_id,
            "case": result.case_id,
            "verdict": result.comparison.verdict,
            "case_result": case_result(result.comparison),
        }
        for result in results
    ]
    print_rows(
        "results",
        rows,
        [
            Col("provider", "Provider"),
            Col("surface", "Surface"),
            Col("model", "Model"),
            Col("case", "Case"),
            Col("verdict", "Verdict"),
            Col("case_result", "Case result"),
        ],
        output_format,
    )
