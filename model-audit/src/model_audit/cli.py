from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Literal

import typer
import yaml
from dotenv import load_dotenv

from model_audit.agent_guides import guide, guides
from model_audit.cases import coverage, load_cases, load_features
from model_audit.catalog import load_catalog
from model_audit.catalog_ops import (
    ModelDefinition,
    add_model,
    add_provider,
    preflight_source,
    provider_sources,
)
from model_audit.catalog_runner import CatalogSyncStep, CatalogTask, SyncComponent, run_catalog_task, sync_catalog
from model_audit.diagnostics import execution_display, feature_display, gap_kind, parity_display, stability_display, validation_failed
from model_audit.drivers import supported_endpoints
from model_audit.evidence import accept, load_ledger, reduce
from model_audit.gateway import Gateway
from model_audit.models import Case, PairResult, Plan, ReportDocument, RunSettings
from model_audit.output import Col, FormatOption, OutputFormat, print_rows
from model_audit.plan import Filters, build_plan
from model_audit.provenance import harness_fingerprint, metadata, new_run_id, taxonomy_fingerprint
from model_audit.report import remaining_plan, restore_plan, write_report
from model_audit.run_service import RunContext, execute_checkpointed
from model_audit.surfaces import discover as discover_surfaces
from model_audit.taxonomy import write as write_taxonomy
from model_audit.taxonomy_diff import compare_taxonomies, summarize_taxonomy_diff

if TYPE_CHECKING:
    from collections.abc import Sequence

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
ProviderSurfaceOption = Annotated[str | None, typer.Option("--provider-surface")]
GatewaySurfaceOption = Annotated[
    list[str] | None,
    typer.Option("--gateway-surface", help="Gateway ingress surface; use all for the complete matrix or repeat for a subset"),
]
TransportOption = Annotated[Literal["buffered", "streamed"] | None, typer.Option("--transport")]
ConcurrencyOption = Annotated[int, typer.Option("--concurrency", min=1, max=100, help="Maximum experiments to run concurrently")]
GatewayUrlOption = Annotated[str | None, typer.Option("--gateway-url", help="Origin of the running TokKeeper data plane")]
GatewayKeyOption = Annotated[str | None, typer.Option("--gateway-api-key", help="Inference key accepted by the running data plane")]
SyncOption = Annotated[
    list[str] | None,
    typer.Option("--only", help="Synchronize only this component; repeat to combine components"),
]


app = typer.Typer(name="tokkeeper-audit", no_args_is_help=True, help="Discover model behavior, compile taxonomy, and find gateway gaps")
agent_app = typer.Typer(name="agent", no_args_is_help=True, help="Versioned operating guides for agents")
cases_app = typer.Typer(name="cases", no_args_is_help=True)
providers_app = typer.Typer(name="providers", no_args_is_help=True)
models_app = typer.Typer(name="models", no_args_is_help=True)
runs_app = typer.Typer(name="runs", no_args_is_help=True)
evidence_app = typer.Typer(name="evidence", no_args_is_help=True)
taxonomy_app = typer.Typer(name="taxonomy", no_args_is_help=True)
reports_app = typer.Typer(name="reports", no_args_is_help=True)
for group in (agent_app, cases_app, providers_app, models_app, runs_app, evidence_app, taxonomy_app, reports_app):
    app.add_typer(group)


def _cases() -> list[Case]:
    features = load_features(FEATURES)
    return load_cases(CASES, features)


def _plan(filters: Filters) -> Plan:
    catalog = load_catalog(ROOT / "taxonomy")
    return build_plan(catalog.targets, _cases(), supported_endpoints(filters.client_mode), filters)


def _surface_selection(surfaces: list[str] | None) -> tuple[str, ...]:
    available = discover_surfaces()
    selected = tuple(surfaces or ())
    invalid = sorted(set(selected) - set(available) - {"all"})
    if invalid:
        choices = ", ".join((*available, "all"))
        message = f"unknown gateway surface {', '.join(invalid)}; choose from {choices}"
        raise typer.BadParameter(message)
    return selected


def _run_task(task: CatalogTask, *arguments: str) -> None:
    result = run_catalog_task(task, *arguments)
    if result.stdout:
        typer.echo(result.stdout.rstrip())
    if result.returncode:
        typer.echo((result.stderr or result.stdout or f"{task} failed").strip(), err=True)
        raise typer.Exit(result.returncode)


def _provider_entries() -> dict[str, dict[str, object]]:
    document = yaml.safe_load((ROOT / "taxonomy" / "providers.yml").read_text(encoding="utf-8"))
    return {str(provider["id"]): provider for provider in document["providers"]}


def _sync_components(values: list[str] | None) -> tuple[SyncComponent, ...]:
    allowed: tuple[SyncComponent, ...] = ("models", "pricing", "schemas", "parameters", "icons")
    requested = tuple(dict.fromkeys(values or allowed))
    invalid = sorted(set(requested) - set(allowed))
    if invalid:
        message = f"unknown sync component {', '.join(invalid)}; choose from {', '.join(allowed)}"
        raise typer.BadParameter(message)
    return tuple(component for component in allowed if component in requested)


def _print_sync(steps: Sequence[CatalogSyncStep], output_format: OutputFormat) -> None:
    rows = [{"provider": step.provider, "component": step.component, "status": step.status, "detail": step.detail} for step in steps]
    print_rows(
        "provider sync steps",
        rows,
        [Col("provider", "Provider"), Col("component", "Component"), Col("status", "Status"), Col("detail", "Detail")],
        output_format,
    )


@agent_app.command("guides")
def agent_guides(output_format: FormatOption = OutputFormat.table) -> None:
    rows = [{"id": item.id, "version": item.version, "title": item.title, "use_when": item.use_when} for item in guides()]
    print_rows(
        "agent guides",
        rows,
        [Col("id", "Guide"), Col("version", "Version"), Col("title", "Title"), Col("use_when", "Use when")],
        output_format,
    )


@agent_app.command("guide")
def agent_guide(
    guide_id: Annotated[str, typer.Argument(help="Guide identifier from agent guides")],
    output_format: FormatOption = OutputFormat.text,
) -> None:
    try:
        item = guide(guide_id)
    except ValueError as error:
        raise typer.BadParameter(str(error)) from error
    if output_format is OutputFormat.json:
        rows = [{"id": item.id, "version": item.version, "title": item.title, "use_when": item.use_when, "body": item.body}]
        print_rows("agent guide", rows, [Col("id", "Guide")], output_format)
        return
    if output_format is OutputFormat.table:
        print_rows(
            "agent guide",
            [{"id": item.id, "version": item.version, "title": item.title, "use_when": item.use_when}],
            [Col("id", "Guide"), Col("version", "Version"), Col("title", "Title"), Col("use_when", "Use when")],
            output_format,
        )
        return
    typer.echo(item.body.rstrip())


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


@providers_app.command("sources")
def providers_sources(output_format: FormatOption = OutputFormat.table) -> None:
    active = set(_provider_entries())
    rows = [
        {
            "id": provider_id,
            "active": "yes" if provider_id in active else "no",
            "definition": "ready" if source.definition is not None else "research required",
            "models_url": str(source.definition.models_url) if source.definition is not None else source.url,
            "schemas": len(source.schemas) + len(source.documented_schemas),
        }
        for provider_id, source in sorted(provider_sources().items())
    ]
    print_rows(
        "provider sources",
        rows,
        [
            Col("id", "Provider"),
            Col("active", "Active"),
            Col("definition", "Definition"),
            Col("models_url", "Models URL"),
            Col("schemas", "Schemas"),
        ],
        output_format,
    )


@providers_app.command("onboard")
def providers_onboard(
    provider_id: Annotated[str, typer.Argument(help="Auto-discovered provider source identifier")],
    replace: Annotated[bool, typer.Option("--replace", help="Replace an active provider from its source definition")] = False,
    output_format: FormatOption = OutputFormat.table,
) -> None:
    load_dotenv(ROOT / ".env")
    source = provider_sources().get(provider_id)
    if source is None:
        message = f"provider source {provider_id} does not exist; run 'tokkeeper-audit agent guide provider-onboarding'"
        raise typer.BadParameter(message)
    definition = source.definition
    if definition is None:
        message = f"provider source {provider_id} has no ProviderDefinition; run 'tokkeeper-audit agent guide provider-onboarding'"
        raise typer.BadParameter(message)
    key = os.environ.get(definition.env_var)
    if not source.open_access and key is None:
        message = f"set {definition.env_var} before onboarding {provider_id}"
        raise typer.BadParameter(message)
    try:
        model_count = preflight_source(source, key)
        provider = add_provider(ROOT, definition, replace=replace)
    except (RuntimeError, ValueError) as error:
        raise typer.BadParameter(str(error)) from error
    steps = [
        CatalogSyncStep(provider=provider.id, component="definition", detail=f"source verified with {model_count} models"),
        *sync_catalog(
            ROOT,
            (provider.id,),
            ("models", "pricing", "schemas", "parameters", "icons"),
            refresh_definitions=False,
        ),
    ]
    _print_sync(steps, output_format)
    if failed := next((step for step in steps if step.returncode), None):
        raise typer.Exit(failed.returncode if failed.component == "seed" else 1)


@providers_app.command("sync")
def providers_sync(
    provider: Annotated[str | None, typer.Argument(help="Provider identifier; omit to synchronize every active provider")] = None,
    only: SyncOption = None,
    output_format: FormatOption = OutputFormat.table,
) -> None:
    load_dotenv(ROOT / ".env")
    entries = _provider_entries()
    if provider is not None and provider not in entries:
        message = f"provider {provider} is not active; use providers onboard first"
        raise typer.BadParameter(message)
    selected = (provider,) if provider is not None else tuple(sorted(entries))
    components = _sync_components(only)
    steps = sync_catalog(ROOT, selected, components)
    _print_sync(steps, output_format)
    if any(step.returncode for step in steps):
        raise typer.Exit(1)


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
    input_modality: Annotated[list[str], typer.Option("--input-modality", help="Accepted input modality; repeat for multiple")],
    output_modality: Annotated[list[str], typer.Option("--output-modality", help="Produced output modality; repeat for multiple")],
    context_window: Annotated[int | None, typer.Option("--context-window", min=1)] = None,
    max_output_tokens: Annotated[int | None, typer.Option("--max-output-tokens", min=1)] = None,
    replace: Annotated[bool, typer.Option("--replace", help="Replace an existing model while preserving discovered metadata")] = False,
) -> None:
    try:
        definition = ModelDefinition.model_validate(
            {
                "id": model,
                "source": source,
                "input_modalities": input_modality,
                "output_modalities": output_modality,
                "context_window": context_window,
                "max_output_tokens": max_output_tokens,
            }
        )
        path = add_model(ROOT, provider, definition, replace=replace)
    except ValueError as error:
        raise typer.BadParameter(str(error)) from error
    _run_task(CatalogTask.discover_parameters)
    write_taxonomy(ROOT)
    typer.echo(f"added {provider}/{model} to {path}")


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


def _print_run_results(results: tuple[PairResult, ...], output_format: OutputFormat) -> None:
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
            "stability": stability_display(result.assessment),
            "execution": execution_display(result.assessment),
            "gap": gap_kind(result),
            "attempts": len(result.attempts),
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
            *((Col("stability", "Stability"),) if any(result.assessment.stability == "flaky" for result in results) else ()),
            *((Col("execution", "Execution"),) if any(result.assessment.execution != "completed" for result in results) else ()),
            Col("gap", "Gap"),
            *((Col("attempts", "Attempts"),) if any(len(result.attempts) > 1 for result in results) else ()),
        ),
        output_format,
    )


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
    transient_retries: Annotated[
        int,
        typer.Option("--transient-retries", min=0, max=5, help="Retries for rate limits and other transient path failures"),
    ] = 2,
    retry_backoff: Annotated[
        float,
        typer.Option("--retry-backoff", min=0, max=60, help="Initial retry delay in seconds; later retries back off exponentially"),
    ] = 2,
    concurrency: ConcurrencyOption = 4,
    request_timeout: Annotated[float, typer.Option("--request-timeout", min=0.1)] = 60,
    output_format: FormatOption = OutputFormat.table,
) -> None:
    load_dotenv(ROOT / ".env")
    gateway_url = gateway_url or os.environ.get("TOKKEEPER_GATEWAY_URL")
    gateway_api_key = gateway_api_key or os.environ.get("TOKKEEPER_INFERENCE_KEY")
    if gateway_url is None or gateway_api_key is None:
        message = "set TOKKEEPER_GATEWAY_URL and TOKKEEPER_INFERENCE_KEY, or pass both gateway options"
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
    maximum_requests = plan.requests * (confirmations + 1) * (transient_retries + 1)
    if maximum_requests > max_requests and not yes:
        message = f"the run can schedule up to {maximum_requests} requests; pass --yes or narrow the selection"
        raise typer.BadParameter(message)
    run_id = new_run_id()
    gateway = Gateway(base_url=gateway_url, api_key=gateway_api_key, request_timeout_seconds=request_timeout)
    settings = RunSettings(
        confirmations=confirmations,
        transient_retries=transient_retries,
        retry_backoff_seconds=retry_backoff,
        request_timeout_seconds=request_timeout,
    )
    results, paths = execute_checkpointed(
        plan,
        (),
        RunContext(
            plan=plan,
            gateway=gateway,
            run=metadata(ROOT, run_id, gateway.base_url),
            settings=settings,
            concurrency=concurrency,
            directory=REPORTS,
        ),
    )
    _print_run_results(results, output_format)
    typer.echo(f"wrote {paths.json_path} and {paths.html_path}", err=True)
    if any(validation_failed(result) for result in results):
        raise typer.Exit(1)


@runs_app.command("resume")
def runs_resume(  # noqa: PLR0913, PLR0917 command flags define the CLI surface
    report: Annotated[Path, typer.Argument(exists=True, dir_okay=False, help="Incomplete JSON report")],
    gateway_api_key: GatewayKeyOption = None,
    confirmations: Annotated[int | None, typer.Option("--confirmations", min=0, max=5)] = None,
    transient_retries: Annotated[
        int | None,
        typer.Option("--transient-retries", min=0, max=5, help="Override retries for transient path failures"),
    ] = None,
    retry_backoff: Annotated[
        float | None,
        typer.Option("--retry-backoff", min=0, max=60, help="Override the initial exponential backoff delay"),
    ] = None,
    concurrency: ConcurrencyOption = 4,
    request_timeout: Annotated[float | None, typer.Option("--request-timeout", min=0.1)] = None,
    output_format: FormatOption = OutputFormat.table,
) -> None:
    load_dotenv(ROOT / ".env")
    document = ReportDocument.model_validate_json(report.read_text(encoding="utf-8"))
    if document.complete:
        typer.echo(f"run {document.run.run_id} is already complete")
        return
    if document.plan is None:
        message = "the report has no stored plan and cannot be resumed"
        raise typer.BadParameter(message)
    fingerprint = taxonomy_fingerprint(ROOT)
    if fingerprint != document.run.taxonomy_fingerprint:
        message = f"taxonomy changed since the run started: expected {document.run.taxonomy_fingerprint}, found {fingerprint}"
        raise typer.BadParameter(message)
    current_harness = harness_fingerprint(ROOT)
    if current_harness != document.run.harness_fingerprint:
        message = f"audit harness changed since the run started: expected {document.run.harness_fingerprint}, found {current_harness}"
        raise typer.BadParameter(message)
    gateway_api_key = gateway_api_key or os.environ.get("TOKKEEPER_INFERENCE_KEY")
    if gateway_api_key is None:
        message = "set TOKKEEPER_INFERENCE_KEY or pass --gateway-api-key"
        raise typer.BadParameter(message)
    pending = remaining_plan(document)
    if not pending.experiments:
        paths = write_report(
            document.model_copy(update={"complete": True}),
            report.parent,
        )
        typer.echo(f"completed checkpoint {paths.json_path}")
        return
    settings = document.settings.model_copy(
        update={
            "confirmations": confirmations if confirmations is not None else document.settings.confirmations,
            "transient_retries": transient_retries if transient_retries is not None else document.settings.transient_retries,
            "retry_backoff_seconds": retry_backoff if retry_backoff is not None else document.settings.retry_backoff_seconds,
            "request_timeout_seconds": request_timeout if request_timeout is not None else document.settings.request_timeout_seconds,
        }
    )
    gateway = Gateway(
        base_url=document.run.gateway_url,
        api_key=gateway_api_key,
        request_timeout_seconds=settings.request_timeout_seconds,
    )
    results, paths = execute_checkpointed(
        pending,
        document.results,
        RunContext(
            plan=restore_plan(document.plan),
            gateway=gateway,
            run=document.run,
            settings=settings,
            concurrency=concurrency,
            directory=report.parent,
        ),
    )
    _print_run_results(results, output_format)
    typer.echo(f"resumed {len(pending.experiments)} experiments; wrote {paths.json_path} and {paths.html_path}", err=True)
    if any(validation_failed(result) for result in results):
        raise typer.Exit(1)


@evidence_app.command("accept")
def evidence_accept(
    report: Annotated[Path, typer.Argument(exists=True, dir_okay=False)],
    replace_ledger: Annotated[bool, typer.Option("--replace-ledger", help="Discard all accepted evidence before adding this report")] = False,
) -> None:
    try:
        added, total, skipped = accept(report, LEDGER, tuple(_cases()), replace=replace_ledger)
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


@taxonomy_app.command("rebuild")
def taxonomy_rebuild(
    preserve_as: Annotated[
        str | None,
        typer.Option("--preserve-as", help="Rename the current taxonomy directory before rebuilding"),
    ] = None,
) -> None:
    load_dotenv(ROOT / ".env")
    taxonomy = ROOT / "taxonomy"
    preserved: Path | None = None
    readme: str | None = None
    if taxonomy.exists():
        if preserve_as is None:
            message = "taxonomy already exists; pass --preserve-as with a new root-level directory name"
            raise typer.BadParameter(message)
        if Path(preserve_as).name != preserve_as or preserve_as in {"", ".", "taxonomy"}:
            message = "--preserve-as must be a new root-level directory name"
            raise typer.BadParameter(message)
        preserved = ROOT / preserve_as
        if preserved.exists():
            message = f"{preserve_as} already exists"
            raise typer.BadParameter(message)
        readme_path = taxonomy / "README.md"
        readme = readme_path.read_text(encoding="utf-8") if readme_path.exists() else None
        taxonomy.rename(preserved)
        typer.echo(f"preserved taxonomy as {preserved.relative_to(ROOT)}")
    elif preserve_as is not None:
        message = "taxonomy does not exist, so there is nothing to preserve"
        raise typer.BadParameter(message)
    try:
        _run_task(CatalogTask.bootstrap)
    finally:
        if readme is not None and taxonomy.exists():
            (taxonomy / "README.md").write_text(readme, encoding="utf-8")


@taxonomy_app.command("validate")
def taxonomy_validate() -> None:
    result = coverage(_cases(), load_features(FEATURES))
    if result.missing or result.missing_endpoint_coverage or result.unmapped_request_fields:
        gaps = (*result.missing, *result.missing_endpoint_coverage, *(f"request:{field}" for field in result.unmapped_request_fields))
        typer.echo(f"missing case coverage: {', '.join(gaps)}", err=True)
        raise typer.Exit(1)
    _run_task(CatalogTask.validate)
    providers, models, changed = write_taxonomy(ROOT, check=True)
    if changed:
        typer.echo("taxonomy is stale; run taxonomy build", err=True)
        raise typer.Exit(1)
    typer.echo(f"audit definitions and taxonomy are valid: {providers} providers, {models} models")


@taxonomy_app.command("diff")
def taxonomy_diff(
    before: Path,
    after: Path,
    summary: Annotated[bool, typer.Option("--summary", help="Show counts instead of field-level changes")] = False,
    output_format: FormatOption = OutputFormat.table,
) -> None:
    for directory in (before, after):
        if not (directory / "providers.yml").exists() or not (directory / "models").is_dir():
            message = f"{directory} is not a taxonomy directory"
            raise typer.BadParameter(message)
    rows = compare_taxonomies(before, after)
    if summary:
        print_rows(
            "taxonomy differences",
            summarize_taxonomy_diff(rows),
            [Col("scope", "Scope"), Col("change", "Change"), Col("count", "Count")],
            output_format,
        )
        return
    print_rows(
        "taxonomy differences",
        rows,
        [
            Col("scope", "Scope"),
            Col("provider", "Provider"),
            Col("model", "Model or file"),
            Col("field", "Field"),
            Col("change", "Change"),
            Col("before", "Before"),
            Col("after", "After"),
        ],
        output_format,
    )


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
            "stability": stability_display(result.assessment),
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
            Col("stability", "Stability"),
            Col("execution", "Execution"),
            Col("gap", "Gap"),
        ],
        output_format,
    )


@reports_app.command("list")
def reports_list(output_format: FormatOption = OutputFormat.table) -> None:
    rows = []
    for path in sorted(REPORTS.glob("*.json"), reverse=True):
        try:
            document = ReportDocument.model_validate_json(path.read_text(encoding="utf-8"))
        except ValueError:
            continue
        rows.append(
            {
                "run": document.run.run_id,
                "created": document.run.created_at,
                "complete": "yes" if document.complete else "no",
                "experiments": len(document.results),
                "size": path.stat().st_size,
                "path": str(path),
            }
        )
    print_rows(
        "reports",
        rows,
        (
            Col("run", "Run"),
            Col("created", "Created"),
            Col("complete", "Complete"),
            Col("experiments", "Experiments"),
            Col("size", "Bytes"),
            Col("path", "Path"),
        ),
        output_format,
    )


@reports_app.command("prune")
def reports_prune(
    keep: Annotated[int, typer.Option("--keep", min=0, help="Number of newest report pairs to retain")] = 20,
    yes: Annotated[bool, typer.Option("--yes", help="Confirm deletion of older report files")] = False,
) -> None:
    reports = sorted(REPORTS.glob("*.json"), key=lambda path: path.stat().st_mtime, reverse=True)
    selected = reports[keep:]
    if selected and not yes:
        message = f"would remove {len(selected)} report pairs; pass --yes to confirm"
        raise typer.BadParameter(message)
    removed = 0
    for path in selected:
        for artifact in (path, path.with_suffix(".html")):
            if artifact.exists():
                artifact.unlink()
                removed += 1
    typer.echo(f"removed {removed} report files; retained {min(keep, len(reports))} runs")
