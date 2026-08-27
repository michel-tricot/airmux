from __future__ import annotations

import html
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from model_audit.diagnostics import difference_details, feature_display, gap_kind, observation_summary, parity_display
from model_audit.models import ReportDocument, ReportPaths, RunMetadata

if TYPE_CHECKING:
    from pathlib import Path

    from model_audit.models import PairResult

STYLE = (
    "body{font-family:ui-sans-serif,system-ui;margin:2rem;color:#17202a}"
    "table{border-collapse:collapse;width:100%}"
    "th,td{padding:.55rem;border-bottom:1px solid #dfe6e9;text-align:left;vertical-align:top}"
    "th{position:sticky;top:0;background:#fff}"
    ".summary{display:flex;gap:1.5rem;flex-wrap:wrap;margin:1rem 0}"
    ".detail td{background:#f8f9fa;font-size:.9rem}"
    "code{display:block;padding:.6rem;background:#eef2f3;overflow:auto}ul{margin:.5rem 0}"
)


def _reproduce(result: PairResult, gateway_url: str) -> str:
    return (
        f"uv run airllm-audit runs execute --model {result.model_id} --surface {result.surface_id} "
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
  <td>{html.escape(result.case_id)}</td><td>{html.escape(result.transport)}</td>
  <td>{html.escape(feature_display(result.assessment))}</td><td>{html.escape(parity_display(result.assessment))}</td>
  <td>{html.escape(gap_kind(result))}</td>
</tr>
<tr class="detail"><td colspan="8">
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
    inconclusive = sum(result.assessment.parity == "inconclusive" for result in results)
    supported = sum(result.assessment.feature == "supported" for result in results)
    unsupported = sum(result.assessment.feature == "unsupported" for result in results)
    unknown = sum(result.assessment.feature == "unknown" for result in results)
    rows = "".join(_result_html(result, document.run.gateway_url) for result in results)
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>AirLLM model audit {html.escape(document.run.run_id)}</title>
<style>{STYLE}</style></head>
<body><h1>AirLLM model audit</h1><p>Run {html.escape(document.run.run_id)} against {html.escape(document.run.gateway_url)}</p>
<div class="summary"><span>Parity: {matched} match, {mismatched} mismatch, {inconclusive} inconclusive</span>
<span>Features: {supported} supported, {unsupported} unsupported, {unknown} unknown</span></div>
<table><thead><tr><th>Provider</th><th>Model</th><th>Surface</th><th>Case</th><th>Transport</th>
<th>Feature</th><th>Parity</th><th>Gap</th></tr></thead><tbody>{rows}</tbody></table></body></html>"""


def write_report(
    results: list[PairResult],
    directory: Path,
    run_id: str,
    run_metadata: RunMetadata | None = None,
) -> ReportPaths:
    directory.mkdir(parents=True, exist_ok=True)
    fallback = RunMetadata(
        run_id=run_id,
        created_at=datetime.now(tz=UTC).isoformat(),
        harness_commit="unknown",
        gateway_url="unknown",
        taxonomy_fingerprint="unknown",
        client_versions={},
    )
    document = ReportDocument(run=run_metadata or fallback, results=tuple(results))
    json_path = directory / f"{run_id}.json"
    html_path = directory / f"{run_id}.html"
    json_path.write_text(document.model_dump_json(indent=2, exclude_none=True) + "\n", encoding="utf-8")
    html_path.write_text(_html(document), encoding="utf-8")
    return ReportPaths(json_path=json_path, html_path=html_path)
