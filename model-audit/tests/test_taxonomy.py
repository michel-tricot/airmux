from __future__ import annotations

from model_audit.models import BehaviorRecord, Claim
from model_audit.taxonomy import _capabilities, _parameter_support


def behavior(dimension: str, name: str, verdict: str, *, surface: str = "oai", profile: dict | None = None) -> BehaviorRecord:
    return BehaviorRecord.model_validate(
        {
            "provider_id": "stub",
            "model_id": "stub/model",
            "surface_id": surface,
            "endpoint": "chat/completions",
            "claim": Claim.model_validate({"dimension": dimension, "name": name, "profile": profile or {}}),
            "verdict": verdict,
            "evidence_ids": ["evidence"],
            "observed_at": "2026-01-01T00:00:00+00:00",
        }
    )


def test_profile_rejection_does_not_erase_a_broader_capability():
    model = {"supports_thinking": True}
    rejected_low_effort = behavior("capability", "reasoning", "unsupported", profile={"effort": "low"})

    assert "reasoning" in _capabilities(model, [rejected_low_effort])


def test_profile_rejection_does_not_mark_an_entire_option_unsupported():
    model = {"parameter_evidence": {"model_discovery": {"support": {"chat/completions": {"reasoning_effort": "supported"}}}}}
    rejected_low_effort = behavior("option", "reasoning_effort", "unsupported", profile={"value": "low"})

    support = _parameter_support(model, "chat/completions", [rejected_low_effort])

    assert support["reasoning_effort"] == "supported"
