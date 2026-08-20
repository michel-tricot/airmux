from __future__ import annotations

import json

from provider_parity.models import Comparison, Observation, PairResult
from provider_parity.report import write_report


def test_report_is_machine_readable_and_self_contained(tmp_path):
    result = PairResult(
        case_id="text.basic",
        provider_id="openai",
        surface_id="oai",
        model_id="openai/gpt-test",
        sdk="openai",
        transport="buffered",
        direct=Observation(outcome="success", text="ok"),
        gateway=Observation(outcome="success", text="ok"),
        comparison=Comparison(verdict="parity", direct_satisfies_oracle=True, gateway_satisfies_oracle=True),
    )

    paths = write_report([result], tmp_path, run_id="run-test")

    payload = json.loads(paths.json_path.read_text())
    html = paths.html_path.read_text()
    assert payload["results"][0]["comparison"]["verdict"] == "parity"
    assert payload["run"]["run_id"] == "run-test"
    assert "openai/gpt-test" in html
    assert "run-test" in html
    assert "Direct observation" in html
    assert "Gateway observation" in html
    assert "Case result" in html
    assert "<td>passed</td>" in html
    assert "success; text=&quot;ok&quot;" in html
