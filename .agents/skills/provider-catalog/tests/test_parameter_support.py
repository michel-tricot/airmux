from __future__ import annotations

import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from parameter_support import classify_parameter_response, resolve_parameter_support


def test_live_probe_wins_over_vendor_documentation():
    evidence = {
        "vendor_docs": {"support": {"responses": {"temperature": "unsupported"}}},
        "live_probe": {"support": {"responses": {"temperature": "supported"}}},
    }
    assert resolve_parameter_support(evidence, "responses") == {"temperature": "supported"}


def test_vendor_documentation_fills_an_unprobed_parameter():
    evidence = {"vendor_docs": {"support": {"responses": {"temperature": "unsupported"}}}}
    assert resolve_parameter_support(evidence, "responses") == {"temperature": "unsupported"}


def test_a_conclusive_unsupported_parameter_error_is_durable_evidence():
    body = '{"error":{"message":"Unsupported parameter: \'temperature\' is not supported with this model."}}'
    assert classify_parameter_response(400, body, "temperature") == "unsupported"


def test_a_dotted_parameter_name_is_recognized():
    body = '{"error":{"message":"Unsupported parameter: \'reasoning.effort\' is not supported with this model."}}'
    assert classify_parameter_response(400, body, "reasoning_effort") == "unsupported"


def test_a_generic_bad_request_is_not_parameter_evidence():
    assert classify_parameter_response(400, '{"error":{"message":"Bad request"}}', "temperature") is None
