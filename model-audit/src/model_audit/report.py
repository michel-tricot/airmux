from __future__ import annotations

import html
import json
from typing import TYPE_CHECKING

from model_audit.diagnostics import (
    difference_details,
    execution_display,
    feature_display,
    gap_kind,
    observation_summary,
    parity_display,
    stability_display,
)
from model_audit.models import Experiment, ExperimentReference, PairResult, Plan, PlanArchive, ReportDocument, ReportPaths, Target

if TYPE_CHECKING:
    from pathlib import Path

STYLE = """
:root {
  color-scheme: dark;
  --background: #080b12;
  --surface: #101621;
  --surface-raised: #151d2a;
  --border: #263246;
  --border-strong: #35435a;
  --text: #edf2f7;
  --muted: #8f9bad;
  --green: #55d6a7;
  --green-soft: #12352d;
  --red: #ff7b86;
  --red-soft: #3d1c25;
  --yellow: #f3c969;
  --yellow-soft: #3b3018;
  --blue: #80bfff;
  --blue-soft: #172e49;
}
* { box-sizing: border-box; }
body {
  margin: 0;
  background:
    radial-gradient(circle at 8% -10%, rgba(58, 105, 170, .22), transparent 32rem),
    var(--background);
  color: var(--text);
  font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  font-size: 14px;
  line-height: 1.5;
}
main { width: min(1480px, calc(100% - 40px)); margin: 0 auto; padding: 48px 0 72px; }
.masthead { display: flex; align-items: flex-end; justify-content: space-between; gap: 32px; margin-bottom: 28px; }
.eyebrow { margin: 0 0 8px; color: var(--blue); font-size: 11px; font-weight: 700; letter-spacing: .14em; text-transform: uppercase; }
h1 { margin: 0; font-size: clamp(28px, 4vw, 42px); letter-spacing: -.04em; line-height: 1.05; }
.run-meta { margin: 12px 0 0; color: var(--muted); }
.run-meta strong { color: var(--text); font-weight: 600; }
.state { flex: 0 0 auto; padding: 7px 11px; border: 1px solid var(--border-strong); border-radius: 999px; color: var(--muted); font-size: 12px; }
.state.complete { border-color: rgba(85, 214, 167, .35); background: var(--green-soft); color: var(--green); }
.metrics { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; margin-bottom: 32px; }
.metric { min-height: 112px; padding: 18px; border: 1px solid var(--border); border-radius: 14px; background: rgba(16, 22, 33, .88); }
.metric-label {
  display: block;
  margin-bottom: 12px;
  color: var(--muted);
  font-size: 11px;
  font-weight: 700;
  letter-spacing: .09em;
  text-transform: uppercase;
}
.metric-value { display: block; font-size: 27px; font-weight: 720; letter-spacing: -.03em; }
.metric-detail { display: block; margin-top: 6px; color: var(--muted); font-size: 12px; }
.metric.good .metric-value { color: var(--green); }
.metric.bad .metric-value { color: var(--red); }
.section-heading { display: flex; align-items: baseline; justify-content: space-between; gap: 24px; margin-bottom: 10px; }
h2 { margin: 0; font-size: 17px; letter-spacing: -.01em; }
.section-heading p { margin: 0; color: var(--muted); font-size: 12px; }
.result-head, summary {
  display: grid;
  grid-template-columns: minmax(250px, 1.35fr) minmax(190px, .8fr) minmax(260px, 1fr);
  gap: 24px;
  align-items: center;
}
.result-head { padding: 0 20px 8px 44px; color: var(--muted); font-size: 10px; font-weight: 700; letter-spacing: .1em; text-transform: uppercase; }
.results { display: grid; gap: 8px; }
.result { border: 1px solid var(--border); border-radius: 12px; background: rgba(16, 22, 33, .9); overflow: hidden; }
.result[open] { border-color: var(--border-strong); background: var(--surface); }
.result.gap-gateway_rejection, .result.gap-semantic, .result.gap-error_mapping,
.result.gap-streaming, .result.gap-translation { border-left: 3px solid var(--red); }
.result.gap-flaky, .result.gap-transient, .result.gap-inconclusive { border-left: 3px solid var(--yellow); }
summary { position: relative; min-height: 76px; padding: 14px 20px 14px 44px; cursor: pointer; list-style: none; }
summary::-webkit-details-marker { display: none; }
summary::before {
  position: absolute;
  left: 20px;
  color: var(--muted);
  content: ">";
  font-size: 22px;
  transform: rotate(0deg);
  transition: transform .15s ease;
}
.result[open] summary::before { transform: rotate(90deg); }
summary:hover { background: rgba(128, 191, 255, .035); }
.identity strong { display: block; overflow: hidden; font-size: 14px; text-overflow: ellipsis; white-space: nowrap; }
.identity small, .route small { display: block; margin-top: 3px; color: var(--muted); font-size: 12px; }
.route { color: #c8d2df; font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size: 12px; }
.badges { display: flex; flex-wrap: wrap; justify-content: flex-end; gap: 6px; }
.badge {
  display: inline-flex;
  align-items: center;
  min-height: 25px;
  padding: 3px 8px;
  border: 1px solid var(--border);
  border-radius: 999px;
  font-size: 11px;
  font-weight: 650;
  white-space: nowrap;
}
.badge.supported, .badge.match, .badge.stable { border-color: rgba(85, 214, 167, .25); background: var(--green-soft); color: var(--green); }
.badge.mismatch, .badge.gateway_rejection, .badge.semantic, .badge.error_mapping,
.badge.streaming, .badge.translation { border-color: rgba(255, 123, 134, .28); background: var(--red-soft); color: var(--red); }
.badge.unsupported, .badge.unknown, .badge.flaky, .badge.not_evaluated, .badge.inconclusive,
.badge.transient, .badge.access_blocked { border-color: rgba(243, 201, 105, .25); background: var(--yellow-soft); color: var(--yellow); }
.details { padding: 0 20px 22px 44px; border-top: 1px solid var(--border); }
.reason { margin: 0 -20px 20px -44px; padding: 13px 20px 13px 44px; background: rgba(128, 191, 255, .045); color: #c7d2df; }
.observation-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }
.panel { min-width: 0; padding: 16px; border: 1px solid var(--border); border-radius: 10px; background: var(--surface-raised); }
.panel h3, .detail-block h3 { margin: 0 0 8px; color: var(--muted); font-size: 10px; letter-spacing: .09em; text-transform: uppercase; }
.panel p { margin: 0; overflow-wrap: anywhere; font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size: 12px; }
.detail-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 20px; margin-top: 20px; }
.detail-block { min-width: 0; }
.pills { display: flex; flex-wrap: wrap; gap: 6px; }
.pill {
  padding: 3px 7px;
  border: 1px solid var(--border);
  border-radius: 6px;
  color: #bcc7d5;
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 11px;
}
.differences { margin: 0; padding-left: 18px; color: #c7d2df; }
.differences li + li { margin-top: 5px; }
.differences strong { color: var(--text); }
.request-details { margin-top: 20px; border: 1px solid var(--border); border-radius: 10px; background: #0b1019; }
.request-details > summary { display: block; min-height: 0; padding: 12px 16px 12px 38px; color: var(--blue); font-size: 12px; }
.request-details > summary::before { left: 15px; font-size: 18px; }
.request-details > .observation-grid { padding: 0 14px 14px; }
.request-details > p {
  margin: 0;
  padding: 0 14px 14px;
  color: var(--muted);
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 11px;
}
.request-details pre { max-height: 360px; margin: 10px 0 0; overflow: auto; color: #b8c4d3; font-size: 11px; white-space: pre-wrap; }
.command {
  display: block;
  margin-top: 20px;
  padding: 13px 15px;
  border: 1px solid var(--border);
  border-radius: 9px;
  background: #080d16;
  color: #b8d9ff;
  overflow-x: auto;
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 12px;
  white-space: pre;
}
.checkpoint { display: grid; min-height: 100vh; place-content: center; }
.checkpoint-card { max-width: 720px; padding: 28px; border: 1px solid var(--border); border-radius: 16px; background: var(--surface); }
.checkpoint-card p { color: var(--muted); }
@media (max-width: 900px) {
  .metrics { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .result-head { display: none; }
  summary { grid-template-columns: 1fr; gap: 10px; }
  .badges { justify-content: flex-start; }
}
@media (max-width: 620px) {
  main { width: min(100% - 24px, 1480px); padding-top: 28px; }
  .masthead { align-items: flex-start; flex-direction: column; gap: 16px; }
  .metrics, .observation-grid, .detail-grid { grid-template-columns: 1fr; }
  summary { padding-left: 38px; }
  summary::before { left: 15px; }
  .details { padding-left: 20px; }
  .reason { margin-left: -20px; padding-left: 20px; }
}
"""


def checkpoint_interval(experiment_count: int) -> int:
    return max(1, (experiment_count + 99) // 100)


def _reproduce(result: PairResult, gateway_url: str) -> str:
    return (
        f"uv run airllm-audit runs execute --model {result.model_id} --provider-surface {result.surface_id} "
        f"--gateway-surface {result.gateway_surface_id} "
        f"--case {result.case_id} --transport {result.transport} --gateway-url {gateway_url}"
    )


def _badge(label: str, value: str) -> str:
    return f'<span class="badge {html.escape(value)}">{html.escape(label)}</span>'


def _result_html(result: PairResult, gateway_url: str) -> str:
    differences = "".join(
        f"<li><strong>{html.escape(detail.label)}</strong>: direct={html.escape(detail.direct)} | gateway={html.escape(detail.gateway)}</li>"
        for detail in difference_details(result)
    )
    difference_block = (
        f'<ul class="differences">{differences}</ul>' if differences else '<span class="metric-detail">No normalized differences</span>'
    )
    claim_verdicts = {claim.claim.key: claim.feature for claim in result.assessment.claims}
    claims = "".join(
        f'<span class="pill">{html.escape(claim.dimension)}:{html.escape(claim.name)} · '
        f"{html.escape(claim_verdicts.get(claim.key, 'unknown'))}</span>"
        for claim in result.claims
    )
    assessment = result.assessment
    gap = gap_kind(result)
    badges = [
        _badge(feature_display(assessment), assessment.feature),
        _badge(parity_display(assessment), assessment.parity),
    ]
    if assessment.stability == "flaky":
        badges.append(_badge(stability_display(assessment), assessment.stability))
    if assessment.execution != "completed":
        badges.append(_badge(execution_display(assessment), assessment.execution))
    if gap != "none":
        badges.append(_badge(gap.replace("_", " "), gap))
    route = f"{result.surface_id} → {result.gateway_surface_id}"
    context = f"{result.transport} · {result.client} · {len(result.attempts)} attempt{'s' if len(result.attempts) != 1 else ''}"
    request_details = ""
    if result.direct_request is not None and result.gateway_request is not None:
        direct_request = html.escape(json.dumps(result.direct_request.redacted_body, indent=2, ensure_ascii=False))
        gateway_request = html.escape(json.dumps(result.gateway_request.redacted_body, indent=2, ensure_ascii=False))
        request_details = f"""
    <details class="request-details"><summary>Rendered requests and fingerprints</summary>
      <div class="observation-grid">
        <section class="panel"><h3>Provider request</h3>
          <p>{html.escape(result.direct_request.body_fingerprint)}</p><pre>{direct_request}</pre></section>
        <section class="panel"><h3>Gateway request</h3>
          <p>{html.escape(result.gateway_request.body_fingerprint)}</p><pre>{gateway_request}</pre></section>
      </div>
      <p>Semantic fingerprint: {html.escape(result.direct_request.semantic_fingerprint)}</p>
    </details>"""
    return f"""
<details class="result gap-{html.escape(gap)}">
  <summary>
    <span class="identity"><strong>{html.escape(result.case_id)}</strong><small>{html.escape(result.model_id)}</small></span>
    <span class="route">{html.escape(route)}<small>{html.escape(context)}</small></span>
    <span class="badges">{"".join(badges)}</span>
  </summary>
  <div class="details">
    <p class="reason">{html.escape(assessment.reason)}</p>
    <div class="observation-grid">
      <section class="panel"><h3>Provider observation</h3><p>{html.escape(observation_summary(result.direct))}</p></section>
      <section class="panel"><h3>Gateway observation</h3><p>{html.escape(observation_summary(result.gateway))}</p></section>
    </div>
    <div class="detail-grid">
      <section class="detail-block"><h3>Claims</h3><div class="pills">{claims}</div></section>
      <section class="detail-block"><h3>Differences</h3>{difference_block}</section>
    </div>
    {request_details}
    <code class="command">{html.escape(_reproduce(result, gateway_url))}</code>
  </div>
</details>"""


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
    mixed = sum(result.assessment.feature == "mixed" for result in results)
    gaps = sum(gap_kind(result) != "none" for result in results)
    rows = "".join(_result_html(result, document.run.gateway_url) for result in results)
    state = "Complete" if document.complete else "Incomplete checkpoint"
    state_class = "complete" if document.complete else "incomplete"
    parity_tone = "good" if mismatched == 0 and inconclusive == 0 and not_evaluated == 0 else "bad"
    feature_tone = "good" if unsupported == 0 and unknown == 0 and mixed == 0 else ""
    stability_tone = "good" if flaky == 0 else "bad"
    resume = (
        ""
        if document.complete
        else f'<code class="command">uv run airllm-audit runs resume model-audit/reports/{html.escape(document.run.run_id)}.json</code>'
    )
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>AirLLM model audit {html.escape(document.run.run_id)}</title>
<meta name="viewport" content="width=device-width, initial-scale=1"><style>{STYLE}</style></head>
<body><main>
<header class="masthead"><div><p class="eyebrow">Gateway behavior audit</p><h1>Model audit</h1>
<p class="run-meta"><strong>{html.escape(document.run.run_id)}</strong> · {html.escape(document.run.gateway_url)}</p></div>
<span class="state {state_class}">{state}</span></header>{resume}
<section class="metrics" aria-label="Audit summary">
  <div class="metric"><span class="metric-label">Experiments</span><span class="metric-value">{len(results)}</span>
    <span class="metric-detail">{gaps} require attention</span></div>
  <div class="metric {parity_tone}"><span class="metric-label">Parity</span><span class="metric-value">{matched} match</span>
    <span class="metric-detail">{mismatched} mismatch · {not_evaluated} not evaluated · {inconclusive} inconclusive</span></div>
  <div class="metric {feature_tone}"><span class="metric-label">Provider features</span><span class="metric-value">{supported} supported</span>
    <span class="metric-detail">{unsupported} unsupported · {mixed} mixed · {unknown} unknown</span></div>
  <div class="metric {stability_tone}"><span class="metric-label">Stability</span><span class="metric-value">{len(results) - flaky} stable</span>
    <span class="metric-detail">Stability: {len(results) - flaky} stable, {flaky} flaky</span></div>
</section>
<section><div class="section-heading"><h2>Experiments</h2><p>Select a row to inspect evidence and reproduce it</p></div>
<div class="result-head"><span>Case and model</span><span>Route</span><span>Verdicts</span></div>
<div class="results">{rows}</div></section>
</main></body></html>"""


def _checkpoint_html(document: ReportDocument) -> str:
    planned = len(document.plan.experiments) if document.plan is not None else len(document.results)
    completed = len(document.results)
    run_id = html.escape(document.run.run_id)
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>AirLLM model audit {run_id}</title>
<meta name="viewport" content="width=device-width, initial-scale=1"><style>{STYLE}</style></head>
<body><main class="checkpoint"><section class="checkpoint-card"><p class="eyebrow">Gateway behavior audit</p><h1>Run interrupted</h1>
<p>{completed} of {planned} experiments completed. Resume the remaining experiments with:</p>
<code class="command">uv run airllm-audit runs resume model-audit/reports/{run_id}.json</code></section></main></body></html>"""


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


def _target_key(target: Target) -> str:
    return f"{target.provider_id}:{target.model_id}:{target.surface_id}"


def archive_plan(plan: Plan) -> PlanArchive:
    targets = {_target_key(experiment.target): experiment.target for experiment in plan.experiments}
    cases = {experiment.case.id: experiment.case for experiment in plan.experiments}
    experiments = tuple(
        ExperimentReference(
            target_key=_target_key(experiment.target),
            case_id=experiment.case.id,
            direct_driver_id=experiment.direct_driver_id,
            gateway_driver_id=experiment.gateway_driver_id,
            gateway_surface_id=experiment.gateway_surface_id,
            gateway_endpoint=experiment.gateway_endpoint,
            transport=experiment.transport,
            direct_request=experiment.direct_request,
            gateway_request=experiment.gateway_request,
        )
        for experiment in plan.experiments
    )
    return PlanArchive(targets=targets, cases=cases, experiments=experiments, unavailable=plan.unavailable)


def restore_plan(plan: PlanArchive) -> Plan:
    return Plan(
        experiments=tuple(
            Experiment(
                target=plan.targets[experiment.target_key],
                case=plan.cases[experiment.case_id],
                direct_driver_id=experiment.direct_driver_id,
                gateway_driver_id=experiment.gateway_driver_id,
                gateway_surface_id=experiment.gateway_surface_id,
                gateway_endpoint=experiment.gateway_endpoint,
                transport=experiment.transport,
                direct_request=experiment.direct_request,
                gateway_request=experiment.gateway_request,
            )
            for experiment in plan.experiments
        ),
        unavailable=plan.unavailable,
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
    plan = restore_plan(document.plan)
    completed = {_result_identity(result) for result in document.results}
    return Plan(experiments=tuple(experiment for experiment in plan.experiments if _experiment_identity(experiment) not in completed))


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
