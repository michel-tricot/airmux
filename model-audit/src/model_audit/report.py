from __future__ import annotations

import html
from typing import TYPE_CHECKING

from model_audit.diagnostics import difference_details, feature_display, gap_kind, observation_summary, parity_display, stability_display
from model_audit.models import Experiment, PairResult, Plan, ReportDocument, ReportPaths

if TYPE_CHECKING:
    from pathlib import Path

STYLE = (
    "body{font-family:ui-sans-serif,system-ui;margin:2rem;color:#17202a}"
    "table{border-collapse:collapse;width:100%}"
    "th,td{padding:.55rem;border-bottom:1px solid #dfe6e9;text-align:left;vertical-align:top}"
    "th{position:sticky;top:0;background:#fff}"
    ".summary{display:flex;gap:1.5rem;flex-wrap:wrap;margin:1rem 0}"
    ".detail td{background:#f8f9fa;font-size:.9rem}"
    "code{display:block;padding:.6rem;background:#eef2f3;overflow:auto}ul{margin:.5rem 0}"
)


def checkpoint_interval(experiment_count: int) -> int:
    return max(1, (experiment_count + 99) // 100)


def _reproduce(result: PairResult, gateway_url: str) -> str:
    return (
        f"uv run airllm-audit runs execute --model {result.model_id} --provider-surface {result.surface_id} "
        f"--gateway-surface {result.gateway_surface_id} "
        f"--case {result.case_id} --transport {result.transport} --gateway-url {gateway_url}"
    )


def _result_html(result: PairResult, gateway_url: str) -> str:
    details = "".join(
        f"<li><strong>{html.escape(detail.label)}</strong>: direct={html.escape(detail.direct)} | gateway={html.escape(detail.gateway)}</li>"
        for detail in difference_details(result)
    )
    claims = ", ".join(f"{claim.dimension}:{claim.name}" for claim in result.claims)
    return f"""
<tr>
  <td>{html.escape(result.provider_id)}</td><td>{html.escape(result.model_id)}</td><td>{html.escape(result.surface_id)}</td>
  <td>{html.escape(result.gateway_surface_id)}</td>
  <td>{html.escape(result.case_id)}</td><td>{html.escape(result.transport)}</td>
  <td>{html.escape(feature_display(result.assessment))}</td><td>{html.escape(parity_display(result.assessment))}</td>
  <td>{html.escape(stability_display(result.assessment))}</td>
  <td>{html.escape(gap_kind(result))}</td>
</tr>
<tr class="detail"><td colspan="10">
  <div><strong>Claims:</strong> {html.escape(claims)}</div>
  <div><strong>Direct:</strong> {html.escape(observation_summary(result.direct))}</div>
  <div><strong>Gateway:</strong> {html.escape(observation_summary(result.gateway))}</div>
  <div><strong>Reason:</strong> {html.escape(result.assessment.reason)}</div>
  <ul>{details}</ul>
  <code>{html.escape(_reproduce(result, gateway_url))}</code>
</td></tr>"""


def _html(document: ReportDocument) -> str:
    results = document.results
    matched = sum(result.assessment.parity == "match" for result in results)
    mismatched = sum(result.assessment.parity == "mismatch" for result in results)
    not_evaluated = sum(result.assessment.parity == "not_evaluated" for result in results)
    inconclusive = sum(result.assessment.parity == "inconclusive" for result in results)
    flaky = sum(result.assessment.stability == "flaky" for result in results)
    supported = sum(result.assessment.feature == "supported" for result in results)
    unsupported = sum(result.assessment.feature == "unsupported" for result in results)
    unknown = sum(result.assessment.feature == "unknown" for result in results)
    rows = "".join(_result_html(result, document.run.gateway_url) for result in results)
    state = "Complete" if document.complete else "Incomplete checkpoint"
    resume = "" if document.complete else f"<code>uv run airllm-audit runs resume model-audit/reports/{html.escape(document.run.run_id)}.json</code>"
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>AirLLM model audit {html.escape(document.run.run_id)}</title>
<style>{STYLE}</style></head>
<body><h1>AirLLM model audit</h1><p>{state}: run {html.escape(document.run.run_id)} against {html.escape(document.run.gateway_url)}</p>{resume}
<div class="summary"><span>Parity: {matched} match, {mismatched} mismatch, {not_evaluated} not evaluated, {inconclusive} inconclusive</span>
<span>Stability: {len(results) - flaky} stable, {flaky} flaky</span>
<span>Features: {supported} supported, {unsupported} unsupported, {unknown} unknown</span></div>
<table><thead><tr><th>Provider</th><th>Model</th><th>Provider Surface</th><th>Gateway Surface</th><th>Case</th><th>Transport</th>
<th>Feature</th><th>Parity</th><th>Stability</th><th>Gap</th></tr></thead><tbody>{rows}</tbody></table></body></html>"""


def _checkpoint_html(document: ReportDocument) -> str:
    planned = len(document.plan.experiments) if document.plan is not None else len(document.results)
    completed = len(document.results)
    run_id = html.escape(document.run.run_id)
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>AirLLM model audit {run_id}</title>
<style>{STYLE}</style></head><body><h1>AirLLM model audit</h1>
<p>Incomplete checkpoint: {completed} of {planned} experiments completed</p>
<code>uv run airllm-audit runs resume model-audit/reports/{run_id}.json</code></body></html>"""


def _experiment_identity(experiment: Experiment) -> tuple[str, ...]:
    target = experiment.target
    client = (
        experiment.direct_driver_id
        if experiment.direct_driver_id == experiment.gateway_driver_id
        else f"{experiment.direct_driver_id}/{experiment.gateway_driver_id}"
    )
    return (
        target.provider_id,
        target.surface_id,
        experiment.gateway_surface_id,
        target.model_id,
        experiment.case.id,
        str(experiment.case.version),
        experiment.transport,
        client,
    )


def _result_identity(result: PairResult) -> tuple[str, ...]:
    return (
        result.provider_id,
        result.surface_id,
        result.gateway_surface_id,
        result.model_id,
        result.case_id,
        str(result.case_version),
        result.transport,
        result.client,
    )


def remaining_plan(document: ReportDocument) -> Plan:
    if document.plan is None:
        message = "the report has no stored plan and cannot be resumed"
        raise ValueError(message)
    completed = {_result_identity(result) for result in document.results}
    return Plan(experiments=tuple(experiment for experiment in document.plan.experiments if _experiment_identity(experiment) not in completed))


def ordered_results(plan: Plan, results: tuple[PairResult, ...]) -> tuple[PairResult, ...]:
    by_identity = {_result_identity(result): result for result in results}
    return tuple(by_identity[identity] for experiment in plan.experiments if (identity := _experiment_identity(experiment)) in by_identity)


def write_checkpoint(document: ReportDocument, directory: Path) -> ReportPaths:
    directory.mkdir(parents=True, exist_ok=True)
    json_path = directory / f"{document.run.run_id}.json"
    html_path = directory / f"{document.run.run_id}.html"
    json_temporary = json_path.with_suffix(".json.tmp")
    html_temporary = html_path.with_suffix(".html.tmp")
    json_temporary.write_text(document.model_dump_json(indent=2, exclude_none=True) + "\n", encoding="utf-8")
    html_temporary.write_text(_checkpoint_html(document), encoding="utf-8")
    json_temporary.replace(json_path)
    html_temporary.replace(html_path)
    return ReportPaths(json_path=json_path, html_path=html_path)


def write_report(document: ReportDocument, directory: Path) -> ReportPaths:
    paths = write_checkpoint(document, directory)
    html_temporary = paths.html_path.with_suffix(".html.tmp")
    html_temporary.write_text(_html(document), encoding="utf-8")
    html_temporary.replace(paths.html_path)
    return paths
