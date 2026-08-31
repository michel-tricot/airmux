from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from model_audit.models import Case


@dataclass(frozen=True)
class ScenarioStep:
    case: Case
    continuation: Literal["independent", "provider_state"]


@dataclass(frozen=True)
class Scenario:
    steps: tuple[ScenarioStep, ...]

    @property
    def request_count(self) -> int:
        return len(self.steps)


def compile_scenario(case: Case) -> Scenario:
    first = ScenarioStep(case=case.model_copy(update={"follow_up": None}), continuation="independent")
    if case.follow_up is None:
        return Scenario(steps=(first,))
    follow_up = case.model_copy(update={"request": case.follow_up, "follow_up": None})
    return Scenario(steps=(first, ScenarioStep(case=follow_up, continuation="provider_state")))
