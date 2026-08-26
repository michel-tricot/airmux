from __future__ import annotations

import html
import json
from collections import Counter
from typing import TYPE_CHECKING

from provider_parity.diagnostics import difference_details, feature_display, observation_summary, parity_display
from provider_parity.models import PairResult, ReportDocument, ReportPaths, RunMetadata

if TYPE_CHECKING:
    from pathlib import Path


def _row(result: PairResult) -> str:
    details = "<br>".join(
        f"<strong>{html.escape(detail.label)}</strong>: direct={html.escape(detail.direct)}, gateway={html.escape(detail.gateway)}"
        for detail in difference_details(result)
    )
    confirmations = "<br>".join(
        f"attempt {index}: {html.escape(attempt.comparison.verdict)}"
        f" ({html.escape(', '.join(attempt.comparison.differences) or 'no differences')});"
        f" direct={html.escape(observation_summary(attempt.direct))}; gateway={html.escape(observation_summary(attempt.gateway))}"
        for index, attempt in enumerate(result.confirmations, start=2)
    )
    return (
        "<tr>"
        f"<td>{html.escape(result.provider_id)}</td>"
        f"<td>{html.escape(result.surface_id)}</td>"
        f"<td>{html.escape(result.model_id)}</td>"
        f"<td>{html.escape(result.sdk)}</td>"
        f"<td>{html.escape(result.case_id)}</td>"
        f"<td>{html.escape(result.transport)}</td>"
        f"<td class='{html.escape(result.comparison.verdict)}'>{html.escape(parity_display(result.comparison))}</td>"
        f"<td>{html.escape(feature_display(result.comparison))}</td>"
        f"<td>{html.escape(result.comparison.reason)}</td>"
        f"<td>{confirmations or 'not needed'}</td>"
        f"<td>{html.escape(observation_summary(result.direct))}</td>"
        f"<td>{html.escape(observation_summary(result.gateway))}</td>"
        f"<td>{details}</td>"
        "</tr>"
    )


def write_report(results: list[PairResult], directory: Path, run_id: str, metadata: RunMetadata | None = None) -> ReportPaths:
    directory.mkdir(parents=True, exist_ok=True)
    json_path = directory / f"{run_id}.json"
    html_path = directory / f"{run_id}.html"
    run = metadata or RunMetadata(run_id=run_id, created_at="", harness_commit="", gateway_url="", taxonomy_fingerprint="", sdk_versions={})
    payload = ReportDocument(run=run, results=tuple(results)).model_dump(mode="json")
    json_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    counts = Counter(result.comparison.verdict for result in results)
    summary = " ".join(f"{name}: {count}" for name, count in sorted(counts.items()))
    rows = "".join(_row(result) for result in results)
    document = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>AirLLM provider parity {html.escape(run_id)}</title>
<style>
body{{font:14px system-ui;margin:2rem;color:#18212b}}table{{border-collapse:collapse;width:100%}}
th,td{{border:1px solid #ccd3da;padding:.5rem;text-align:left;vertical-align:top}}th{{background:#eef2f5}}
.parity{{color:#087830}}.gateway_regression,.different{{color:#b42318;font-weight:700}}
.expected_difference,.gateway_only_success{{color:#9a6700}}code{{background:#eef2f5;padding:.2rem}}
</style>
</head><body><h1>Provider parity</h1><p><code>{html.escape(run_id)}</code></p>
<p>Gateway <code>{html.escape(run.gateway_url)}</code>,
harness <code>{html.escape(run.harness_commit)}</code>,
taxonomy <code>{html.escape(run.taxonomy_fingerprint)}</code></p>
<p>{html.escape(summary)}</p>
<table><thead><tr>
<th>Provider</th><th>Surface</th><th>Model</th><th>Client</th><th>Case</th><th>Transport</th><th>Parity</th>
<th>Feature</th><th>Reason</th><th>Confirmations</th><th>Direct observation</th><th>Gateway observation</th><th>Differences</th>
</tr></thead>
<tbody>{rows}</tbody></table></body></html>
"""
    html_path.write_text(document, encoding="utf-8")
    return ReportPaths(json_path=json_path, html_path=html_path)
