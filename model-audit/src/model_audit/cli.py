from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Literal

import typer
import yaml
from dotenv import load_dotenv

from model_audit.cases import coverage, load_cases, load_features
from model_audit.catalog import SURFACES, load_catalog
from model_audit.catalog_ops import ModelDefinition, add_model, add_provider, run_catalog_script
from model_audit.diagnostics import execution_display, feature_display, gap_kind, parity_display, validation_failed
from model_audit.drivers import supported_endpoints
from model_audit.evidence import accept, load_ledger, reduce
from model_audit.gateway import Gateway
from model_audit.models import Case, Plan, ReportDocument
from model_audit.output import Col, FormatOption, OutputFormat, print_rows
from model_audit.plan import Filters, build_plan
from model_audit.progress import ConsoleProgress
from model_audit.provenance import metadata
from model_audit.report import write_report
from model_audit.runner import ExecutionOptions, execute
from model_audit.taxonomy import write as write_taxonomy

ROOT = Path(__file__).resolve().parents[3]
PROJECT = ROOT / "model-audit"
CASES = PROJECT / "cases"
FEATURES = PROJECT / "definitions" / "features.yml"
REPORTS = PROJECT / "reports"
LEDGER = PROJECT / "evidence" / "accepted.json"

ProviderOption = Annotated[str | None, typer.Option("--provider", help="Select every cataloged model from one provider")]
ModelOption = Annotated[str | None, typer.Option("--model")]
CaseOption = Annotated[
    list[str] | None,
    typer.Option("--case", help="Select an exact case or a namespace such as modalities; repeat to combine selections"),
]
SDKOption = Annotated[bool, typer.Option("--sdk", help="Use the matching vendor SDK instead of direct HTTP API calls")]
ProviderSurfaceOption = Annotated[Literal["oai", "oai_responses", "anthropic"] | None, typer.Option("--provider-surface")]
GatewaySurfaceOption = Annotated[
    list[str] | None,
    typer.Option("--gateway-surface", help="Gateway ingress surface; use all for the complete matrix or repeat for a subset"),
]
TransportOption = Annotated[Literal["buffered", "streamed"] | None, typer.Option("--transport")]
ConcurrencyOption = Annotated[int, typer.Option("--concurrency", min=1, max=32, help="Maximum experiments to run concurrently")]
GatewayUrlOption = Annotated[str | None, typer.Option("--gateway-url", help="Origin of the running AirLLM data plane")]
GatewayKeyOption = Annotated[str | None, typer.Option("--gateway-api-key", help="Inference key accepted by the running data plane")]

app = typer.Typer(name="airllm-audit", no_args_is_help=True, help="Discover model behavior, compile taxonomy, and find gateway gaps")
cases_app = typer.Typer(name="cases", no_args_is_help=True)
providers_app = typer.Typer(name="providers", no_args_is_help=True)
models_app = typer.Typer(name="models", no_args_is_help=True)
runs_app = typer.Typer(name="runs", no_args_is_help=True)
evidence_app = typer.Typer(name="evidence", no_args_is_help=True)
taxonomy_app = typer.Typer(name="taxonomy", no_args_is_help=True)
reports_app = typer.Typer(name="reports", no_args_is_help=True)
for group in (cases_app, providers_app, models_app, runs_app, evidence_app, taxonomy_app, reports_app):
    app.add_typer(group)


def _cases() -> list[Case]:
    features = load_features(FEATURES)
    return load_cases(CASES, features)


def _plan(filters: Filters) -> Plan:
    catalog = load_catalog(ROOT / "taxonomy")
    return build_plan(catalog.targets, _cases(), supported_endpoints(filters.client_mode), filters)


def _surface_selection(surfaces: list[str] | None) -> tuple[str, ...]:
    selected = tuple(surfaces or ())
    invalid = sorted(set(selected) - set(SURFACES) - {"all"})
    if invalid:
        choices = ", ".join((*SURFACES, "all"))
        message = f"unknown gateway surface {', '.join(invalid)}; choose from {choices}"
        raise typer.BadParameter(message)
    return selected


def _run_script(script: str, *arguments: str) -> None:
    result = run_catalog_script(ROOT, script, *arguments)
    if result.stdout:
        typer.echo(result.stdout.rstrip())
    if result.returncode:
        typer.echo((result.stderr or result.stdout or f"{script} failed").strip(), err=True)
        raise typer.Exit(result.returncode)


@cases_app.command("list")
def cases_list(output_format: FormatOption = OutputFormat.table) -> None:
    rows = [
        {
            "id": case.id,
            "title": case.title,
            "claims": ", ".join(f"{claim.dimension}:{claim.name}" for claim in case.claims),
            "endpoints": ", ".join(sorted(case.applies_to.endpoints)) or "all",
            "transports": ", ".join(case.transports),
        }
        for case in _cases()
    ]
    print_rows(
        "cases",
        rows,
        [Col("id", "Case"), Col("title", "Title"), Col("claims", "Claims"), Col("endpoints", "Endpoints"), Col("transports", "Transports")],
        output_format,
    )


@cases_app.command("coverage")
def cases_coverage(output_format: FormatOption = OutputFormat.table) -> None:
    result = coverage(_cases(), load_features(FEATURES))
    rows = (
        [{"claim": claim, "status": "covered"} for claim in result.covered]
        + [{"claim": claim, "status": "missing"} for claim in result.missing]
        + [{"claim": claim, "status": "missing endpoint"} for claim in result.missing_endpoint_coverage]
        + [{"claim": claim, "status": "excluded"} for claim in result.excluded]
        + [{"claim": f"request:{field}", "status": "unmapped"} for field in result.unmapped_request_fields]
    )
    print_rows("case coverage", rows, [Col("claim", "Claim"), Col("status", "Status")], output_format)
    typer.echo(
        f"{result.case_count} cases, {len(result.covered)} required claims covered, {len(result.missing)} missing, "
        f"{len(result.missing_endpoint_coverage)} endpoint gaps, "
        f"{len(result.excluded)} explicit exclusions, {len(result.unmapped_request_fields)} unmapped request fields",
        err=True,
    )
    if result.missing or result.missing_endpoint_coverage or result.unmapped_request_fields:
        raise typer.Exit(1)


@providers_app.command("list")
def providers_list(output_format: FormatOption = OutputFormat.table) -> None:
    document = yaml.safe_load((ROOT / "taxonomy" / "providers.yml").read_text(encoding="utf-8"))
    rows = [
        {
            "id": provider["id"],
            "name": provider["name"],
            "surfaces": ", ".join(provider["ingress"]),
            "credential": provider["env_var"],
            "models_url": provider["models_url"],
        }
        for provider in document["providers"]
    ]
    print_rows(
        "providers",
        rows,
        [Col("id", "Provider"), Col("name", "Name"), Col("surfaces", "Surfaces"), Col("credential", "Credential"), Col("models_url", "Models URL")],
        output_format,
    )


@providers_app.command("add")
def providers_add(
    definition: Annotated[Path, typer.Argument(exists=True, dir_okay=False, help="Provider definition YAML")],
    refresh: Annotated[bool, typer.Option("--refresh/--no-refresh", help="Fetch the provider catalog after adding it")] = True,
    replace: Annotated[bool, typer.Option("--replace", help="Replace an existing provider definition")] = False,
) -> None:
    try:
        provider = add_provider(ROOT, definition, replace=replace)
    except ValueError as error:
        raise typer.BadParameter(str(error)) from error
    typer.echo(f"added {provider.id}; credential: {provider.env_var}")
    if refresh:
        _run_script("extract_schemas.py")
        _run_script("doc_schemas.py")
        _run_script("bootstrap.py", "--yaml")
        _run_script("fetch_icons.py")
        _run_script("fetch_models.py", provider.id)
        _run_script("enrich.py")
        _run_script("discover_parameters.py")
        write_taxonomy(ROOT)


@providers_app.command("refresh")
def providers_refresh(provider: Annotated[str | None, typer.Argument()] = None) -> None:
    arguments = (provider,) if provider else ()
    _run_script("extract_schemas.py")
    _run_script("doc_schemas.py")
    _run_script("bootstrap.py", "--yaml")
    _run_script("fetch_models.py", *arguments)
    _run_script("enrich.py")
    _run_script("discover_parameters.py")
    write_taxonomy(ROOT)


@models_app.command("list")
def models_list(
    provider: ProviderOption = None,
    model: ModelOption = None,
    provider_surface: ProviderSurfaceOption = None,
    output_format: FormatOption = OutputFormat.table,
) -> None:
    targets = load_catalog(ROOT / "taxonomy").targets
    rows = [
        {
            "provider": target.provider_id,
            "model": target.model_id,
            "surface": target.surface_id,
            "endpoint": target.endpoint,
            "context": target.context_window or "unknown",
        }
        for target in targets
        if (provider is None or target.provider_id == provider)
        and (model is None or target.model_id == model)
        and (provider_surface is None or target.surface_id == provider_surface)
    ]
    print_rows(
        "models",
        rows,
        [Col("provider", "Provider"), Col("model", "Model"), Col("surface", "Surface"), Col("endpoint", "Endpoint"), Col("context", "Context")],
        output_format,
    )


@models_app.command("add")
def models_add(  # noqa: PLR0913, PLR0917 command flags define the CLI surface
    provider: Annotated[str, typer.Argument()],
    model: Annotated[str, typer.Argument()],
    source: Annotated[str, typer.Option("--source", help="Vendor page or API response supporting this model")],
    context_window: Annotated[int | None, typer.Option("--context-window", min=1)] = None,
    max_output_tokens: Annotated[int | None, typer.Option("--max-output-tokens", min=1)] = None,
    replace: Annotated[bool, typer.Option("--replace", help="Replace an existing model while preserving discovered metadata")] = False,
) -> None:
    definition = ModelDefinition(id=model, source=source, context_window=context_window, max_output_tokens=max_output_tokens)
    try:
        path = add_model(ROOT, provider, definition, replace=replace)
    except ValueError as error:
        raise typer.BadParameter(str(error)) from error
    _run_script("discover_parameters.py")
    write_taxonomy(ROOT)
    typer.echo(f"added {provider}/{model} to {path}")


@models_app.command("refresh")
def models_refresh(provider: Annotated[str | None, typer.Argument()] = None) -> None:
    _run_script("fetch_models.py", *((provider,) if provider else ()))
    _run_script("enrich.py")
    _run_script("discover_parameters.py")
    write_taxonomy(ROOT)


@runs_app.command("plan")
def runs_plan(  # noqa: PLR0913, PLR0917 command flags define the CLI surface
    provider: ProviderOption = None,
    model: ModelOption = None,
    case: CaseOption = None,
    sdk: SDKOption = False,
    provider_surface: ProviderSurfaceOption = None,
    gateway_surface: GatewaySurfaceOption = None,
    transport: TransportOption = None,
    output_format: FormatOption = OutputFormat.table,
) -> None:
    plan = _plan(
        Filters(
            provider=provider,
            model=model,
            cases=tuple(case or ()),
            client_mode="sdk" if sdk else "api",
            direct_surface=provider_surface,
            gateway_surfaces=_surface_selection(gateway_surface),
            transport=transport,
        )
    )
    rows = [
        {
            "provider": experiment.target.provider_id,
            "model": experiment.target.model_id,
            "provider_surface": experiment.target.surface_id,
            "gateway_surface": experiment.gateway_surface_id,
            "route": f"{experiment.target.surface_id} -> {experiment.gateway_surface_id}",
            "clients": (
                experiment.direct_driver_id
                if experiment.direct_driver_id == experiment.gateway_driver_id
                else f"{experiment.direct_driver_id} -> {experiment.gateway_driver_id}"
            ),
            "case": experiment.case.id,
            "transport": experiment.transport,
        }
        for experiment in plan.experiments
    ]
    print_rows(
        "experiments",
        rows,
        [
            Col("model", "Model"),
            Col("route", "Provider -> Gateway"),
            Col("clients", "Client"),
            Col("case", "Case"),
            Col("transport", "Transport"),
        ],
        output_format,
    )
    typer.echo(f"{len(plan.experiments)} paired experiments, {plan.requests} requests, {plan.unavailable} unavailable", err=True)


@runs_app.command("execute")
def runs_execute(  # noqa: PLR0913, PLR0917 command flags define the CLI surface
    provider: ProviderOption = None,
    model: ModelOption = None,
    case: CaseOption = None,
    sdk: SDKOption = False,
    provider_surface: ProviderSurfaceOption = None,
    gateway_surface: GatewaySurfaceOption = None,
    transport: TransportOption = None,
    gateway_url: GatewayUrlOption = None,
    gateway_api_key: GatewayKeyOption = None,
    yes: Annotated[bool, typer.Option("--yes", help="Confirm a run above the request guardrail")] = False,
    max_requests: Annotated[int, typer.Option("--max-requests", min=1)] = 500,
    confirmations: Annotated[int, typer.Option("--confirmations", min=0, max=5)] = 1,
    concurrency: ConcurrencyOption = 4,
    request_timeout: Annotated[float, typer.Option("--request-timeout", min=0.1)] = 60,
    output_format: FormatOption = OutputFormat.table,
) -> None:
    load_dotenv(ROOT / ".env")
    gateway_url = gateway_url or os.environ.get("AIRLLM_GATEWAY_URL")
    gateway_api_key = gateway_api_key or os.environ.get("AIRLLM_API_KEY")
    if gateway_url is None or gateway_api_key is None:
        message = "set AIRLLM_GATEWAY_URL and AIRLLM_API_KEY, or pass both gateway options"
        raise typer.BadParameter(message)
    plan = _plan(
        Filters(
            provider=provider,
            model=model,
            cases=tuple(case or ()),
            client_mode="sdk" if sdk else "api",
            direct_surface=provider_surface,
            gateway_surfaces=_surface_selection(gateway_surface),
            transport=transport,
        )
    )
    if not plan.experiments:
        message = "the selected run has no applicable experiments"
        raise typer.BadParameter(message)
    maximum_requests = plan.requests * (confirmations + 1)
    if maximum_requests > max_requests and not yes:
        message = f"the run can schedule up to {maximum_requests} requests; pass --yes or narrow the selection"
        raise typer.BadParameter(message)
    gateway = Gateway(base_url=gateway_url, api_key=gateway_api_key, request_timeout_seconds=request_timeout)
    progress = ConsoleProgress()
    progress.start(plan, gateway.base_url, confirmations, concurrency)
    results = execute(
        plan,
        gateway,
        progress=progress,
        options=ExecutionOptions(confirmations=confirmations, request_timeout_seconds=request_timeout, concurrency=concurrency),
    )
    run_id = datetime.now(tz=UTC).strftime("%Y%m%dT%H%M%SZ")
    paths = write_report(results, REPORTS, run_id, metadata(ROOT, run_id, gateway.base_url))
    rows = [
        {
            "provider": result.provider_id,
            "model": result.model_id,
            "provider_surface": result.surface_id,
            "gateway_surface": result.gateway_surface_id,
            "route": f"{result.surface_id} -> {result.gateway_surface_id}",
            "case": result.case_id,
            "feature": feature_display(result.assessment),
            "parity": parity_display(result.assessment),
            "execution": execution_display(result.assessment),
            "gap": gap_kind(result),
            "attempts": len(result.confirmations) + 1,
        }
        for result in results
    ]
    print_rows(
        "results",
        rows,
        (
            Col("model", "Model"),
            Col("route", "Provider -> Gateway"),
            Col("case", "Case"),
            Col("feature", "Feature"),
            Col("parity", "Parity"),
            *((Col("execution", "Execution"),) if any(result.assessment.execution != "completed" for result in results) else ()),
            Col("gap", "Gap"),
            *((Col("attempts", "Attempts"),) if any(result.confirmations for result in results) else ()),
        ),
        output_format,
    )
    typer.echo(f"wrote {paths.json_path} and {paths.html_path}", err=True)
    if any(validation_failed(result) for result in results):
        raise typer.Exit(1)


@evidence_app.command("accept")
def evidence_accept(report: Annotated[Path, typer.Argument(exists=True, dir_okay=False)]) -> None:
    try:
        added, total, skipped = accept(report, LEDGER, tuple(_cases()))
    except ValueError as error:
        raise typer.BadParameter(str(error)) from error
    providers, models, _ = write_taxonomy(ROOT)
    typer.echo(f"accepted {added} new observations; skipped {skipped} unusable direct observations; ledger contains {total}")
    typer.echo(f"taxonomy current: {providers} providers, {models} models")


@evidence_app.command("list")
def evidence_list(model: ModelOption = None, output_format: FormatOption = OutputFormat.table) -> None:
    behaviors = reduce(load_ledger(LEDGER), tuple(_cases())).behaviors
    rows = [
        {
            "provider": behavior.provider_id,
            "model": behavior.model_id,
            "surface": behavior.surface_id,
            "claim": f"{behavior.claim.dimension}:{behavior.claim.name}",
            "verdict": behavior.verdict,
            "observed": behavior.observed_at,
        }
        for behavior in behaviors
        if model is None or behavior.model_id == model
    ]
    print_rows(
        "evidence",
        rows,
        [
            Col("provider", "Provider"),
            Col("model", "Model"),
            Col("surface", "Surface"),
            Col("claim", "Claim"),
            Col("verdict", "Verdict"),
            Col("observed", "Observed"),
        ],
        output_format,
    )


@taxonomy_app.command("build")
def taxonomy_build(check: Annotated[bool, typer.Option("--check")] = False) -> None:
    providers, models, changed = write_taxonomy(ROOT, check=check)
    if check and changed:
        typer.echo("taxonomy is stale", err=True)
        raise typer.Exit(1)
    state = "would change" if check and changed else "current" if not changed else "written"
    typer.echo(f"taxonomy {state}: {providers} providers, {models} models")


@taxonomy_app.command("validate")
def taxonomy_validate() -> None:
    result = coverage(_cases(), load_features(FEATURES))
    if result.missing or result.missing_endpoint_coverage or result.unmapped_request_fields:
        gaps = (*result.missing, *result.missing_endpoint_coverage, *(f"request:{field}" for field in result.unmapped_request_fields))
        typer.echo(f"missing case coverage: {', '.join(gaps)}", err=True)
        raise typer.Exit(1)
    _run_script("validate.py")
    providers, models, changed = write_taxonomy(ROOT, check=True)
    if changed:
        typer.echo("taxonomy is stale; run taxonomy build", err=True)
        raise typer.Exit(1)
    typer.echo(f"audit definitions and taxonomy are valid: {providers} providers, {models} models")


def _report(path: Path | None) -> ReportDocument:
    candidates = sorted(REPORTS.glob("*.json"))
    selected = path or (candidates[-1] if candidates else None)
    if selected is None:
        message = "no audit report exists"
        raise typer.BadParameter(message)
    return ReportDocument.model_validate_json(selected.read_text(encoding="utf-8"))


@reports_app.command("show")
def reports_show(
    path: Path | None = None, gaps_only: Annotated[bool, typer.Option("--gaps")] = False, output_format: FormatOption = OutputFormat.table
) -> None:
    results = _report(path).results
    rows = [
        {
            "provider": result.provider_id,
            "model": result.model_id,
            "surface": result.surface_id,
            "case": result.case_id,
            "feature": feature_display(result.assessment),
            "parity": parity_display(result.assessment),
            "execution": execution_display(result.assessment),
            "gap": gap_kind(result),
        }
        for result in results
        if not gaps_only or gap_kind(result) != "none"
    ]
    print_rows(
        "results",
        rows,
        [
            Col("provider", "Provider"),
            Col("model", "Model"),
            Col("surface", "Surface"),
            Col("case", "Case"),
            Col("feature", "Feature"),
            Col("parity", "Parity"),
            Col("execution", "Execution"),
            Col("gap", "Gap"),
        ],
        output_format,
    )
