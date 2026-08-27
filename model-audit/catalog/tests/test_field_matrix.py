from __future__ import annotations

import json
from pathlib import Path


def test_airllm_leads_the_request_field_matrices_and_openrouter_is_absent():
    taxonomy = Path(__file__).resolve().parents[3] / "taxonomy"
    for ingress in ("oai", "anthropic"):
        report = json.loads((taxonomy / "reports" / f"{ingress}-request-fields.json").read_text())
        column_ids = [column["id"] for column in report["columns"]]

        assert column_ids[0] == "airllm"
        assert "openrouter" not in column_ids
        assert b"\r" not in (taxonomy / "reports" / f"{ingress}-request-fields.csv").read_bytes()
