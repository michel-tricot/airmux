from __future__ import annotations

import json
from collections import defaultdict
from hashlib import sha256
from typing import TYPE_CHECKING

from model_audit.cases import fingerprint
from model_audit.compare import ACCESS_CODES, HARNESS_CODES
from model_audit.models import BehaviorRecord, BehaviorTaxonomy, Case, EvidenceLedger, EvidenceRecord, PairResult, ReportDocument

if TYPE_CHECKING:
    from pathlib import Path


def load_ledger(path: Path) -> EvidenceLedger:
    if not path.exists():
        return EvidenceLedger()
    return EvidenceLedger.model_validate_json(path.read_text(encoding="utf-8"))


def _active_cases(cases: tuple[Case, ...]) -> dict[str, tuple[int, str]]:
    return {case.id: (case.version, fingerprint(case)) for case in cases}


def _usable_direct_observation(result: PairResult) -> bool:
    return result.direct.outcome not in {"inconclusive", "transient"} and result.direct.error_code not in ACCESS_CODES | HARNESS_CODES


def records_from_report(report: ReportDocument, cases: tuple[Case, ...]) -> tuple[EvidenceRecord, ...]:
    if not report.complete:
        message = "report is incomplete; resume it before accepting evidence"
        raise ValueError(message)
    active = _active_cases(cases)
    stale = sorted(result.case_id for result in report.results if active.get(result.case_id) != (result.case_version, result.case_fingerprint))
    if stale:
        message = f"report contains stale or unknown cases: {', '.join(stale)}"
        raise ValueError(message)
    records = []
    for result in report.results:
        if result.client != "http":
            message = "SDK runs cannot be promoted as provider behavior evidence"
            raise ValueError(message)
        if not _usable_direct_observation(result):
            continue
        for claim in result.claims:
            identity = f"{report.run.run_id}:{result.model_id}:{result.surface_id}:{result.case_id}:{result.transport}:{claim.key}"
            records.append(
                EvidenceRecord(
                    evidence_id=sha256(identity.encode()).hexdigest()[:24],
                    provider_id=result.provider_id,
                    model_id=result.model_id,
                    upstream_model=result.upstream_model,
                    surface_id=result.surface_id,
                    endpoint=result.endpoint,
                    case_id=result.case_id,
                    case_version=result.case_version,
                    case_fingerprint=result.case_fingerprint,
                    claim=claim,
                    verdict=result.assessment.feature,
                    observation=result.direct,
                    attempts=max(1, len(result.attempts)),
                    observed_at=report.run.created_at,
                    harness_commit=report.run.harness_commit,
                    taxonomy_fingerprint=report.run.taxonomy_fingerprint,
                )
            )
    return tuple(records)


def accept(report_path: Path, ledger_path: Path, cases: tuple[Case, ...]) -> tuple[int, int, int]:
    report = ReportDocument.model_validate_json(report_path.read_text(encoding="utf-8"))
    previous = load_ledger(ledger_path)
    incoming = records_from_report(report, cases)
    eligible_results = sum(_usable_direct_observation(result) for result in report.results)
    skipped = len(report.results) - eligible_results
    records = {record.evidence_id: record for record in previous.records}
    before = len(records)
    records.update({record.evidence_id: record for record in incoming})
    ordered = tuple(sorted(records.values(), key=lambda record: (record.observed_at, record.evidence_id)))
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    ledger_path.write_text(EvidenceLedger(records=ordered).model_dump_json(indent=2, exclude_none=True) + "\n", encoding="utf-8")
    return len(records) - before, len(records), skipped


def reduce(ledger: EvidenceLedger, cases: tuple[Case, ...]) -> BehaviorTaxonomy:
    active = _active_cases(cases)
    grouped: dict[tuple[str, str, str, str], list[EvidenceRecord]] = defaultdict(list)
    for record in ledger.records:
        if active.get(record.case_id) != (record.case_version, record.case_fingerprint):
            continue
        grouped[(record.provider_id, record.model_id, record.surface_id, record.claim.key)].append(record)
    behaviors = []
    for records in grouped.values():
        ordered = sorted(records, key=lambda record: (record.observed_at, record.evidence_id))
        conclusive = [record for record in ordered if record.verdict != "unknown"]
        candidates = conclusive or ordered
        latest_at = candidates[-1].observed_at
        latest = [record for record in candidates if record.observed_at == latest_at]
        verdicts = {record.verdict for record in latest}
        verdict = verdicts.pop() if len(verdicts) == 1 else "unknown"
        representative = latest[-1]
        behaviors.append(
            BehaviorRecord(
                provider_id=representative.provider_id,
                model_id=representative.model_id,
                surface_id=representative.surface_id,
                endpoint=representative.endpoint,
                claim=representative.claim,
                verdict=verdict,
                evidence_ids=tuple(record.evidence_id for record in latest),
                observed_at=latest_at,
            )
        )
    ordered_behaviors = tuple(
        sorted(behaviors, key=lambda behavior: (behavior.provider_id, behavior.model_id, behavior.surface_id, behavior.claim.key))
    )
    fingerprint = sha256(json.dumps([record.model_dump(mode="json") for record in ordered_behaviors], sort_keys=True).encode()).hexdigest()[:16]
    return BehaviorTaxonomy(generated_from=fingerprint, behaviors=ordered_behaviors)


def write_behavior(ledger_path: Path, output_path: Path, cases: tuple[Case, ...]) -> BehaviorTaxonomy:
    behavior = reduce(load_ledger(ledger_path), cases)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(behavior.model_dump(mode="json"), indent=2, sort_keys=False) + "\n", encoding="utf-8")
    return behavior
