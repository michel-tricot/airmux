from __future__ import annotations

from collections import Counter
from hashlib import sha256
from typing import TYPE_CHECKING, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from model_audit.models import Case, ClaimDimension, Request

if TYPE_CHECKING:
    from pathlib import Path


class FeatureDefinition(BaseModel):
    model_config = ConfigDict(frozen=True)

    dimension: ClaimDimension
    name: str
    description: str
    required: bool = True
    endpoints: tuple[Literal["chat/completions", "responses", "messages"], ...] = ("chat/completions", "responses", "messages")
    request_fields: tuple[str, ...] = ()
    exclusion: str | None = None

    @model_validator(mode="after")
    def explain_exclusion(self) -> FeatureDefinition:
        if not self.required and not self.exclusion:
            message = f"optional feature {self.dimension}:{self.name} needs an exclusion reason"
            raise ValueError(message)
        return self


class FeatureCatalog(BaseModel):
    model_config = ConfigDict(frozen=True)

    features: tuple[FeatureDefinition, ...] = Field(min_length=1)


class Coverage(BaseModel):
    model_config = ConfigDict(frozen=True)

    covered: tuple[str, ...]
    missing: tuple[str, ...]
    missing_endpoint_coverage: tuple[str, ...]
    excluded: tuple[str, ...]
    unmapped_request_fields: tuple[str, ...]
    case_count: int


def load_features(path: Path) -> FeatureCatalog:
    catalog = FeatureCatalog.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
    keys = [(feature.dimension, feature.name) for feature in catalog.features]
    duplicates = sorted(f"{dimension}:{name}" for dimension, name in set(keys) if keys.count((dimension, name)) > 1)
    if duplicates:
        message = f"duplicate feature definitions: {', '.join(duplicates)}"
        raise ValueError(message)
    return catalog


def load_cases(path: Path, features: FeatureCatalog | None = None) -> list[Case]:
    cases = [Case.model_validate(yaml.safe_load(case.read_text(encoding="utf-8"))) for case in sorted(path.rglob("*.yml"))]
    counts = Counter(case.id for case in cases)
    duplicates = sorted(case_id for case_id, count in counts.items() if count > 1)
    if duplicates:
        message = f"duplicate case ids: {', '.join(duplicates)}"
        raise ValueError(message)
    if features is not None:
        known = {(feature.dimension, feature.name) for feature in features.features}
        unknown = sorted(
            f"{case.id} -> {claim.dimension}:{claim.name}" for case in cases for claim in case.claims if (claim.dimension, claim.name) not in known
        )
        if unknown:
            message = f"cases use undefined claims: {', '.join(unknown)}"
            raise ValueError(message)
    empty_oracles = sorted(case.id for case in cases if not case.oracle.has_assertion)
    if empty_oracles:
        message = f"cases need a semantic oracle: {', '.join(empty_oracles)}"
        raise ValueError(message)
    return cases


def fingerprint(case: Case) -> str:
    return sha256(case.model_dump_json().encode()).hexdigest()[:16]


def coverage(cases: list[Case], features: FeatureCatalog) -> Coverage:
    claimed = {(claim.dimension, claim.name) for case in cases for claim in case.claims}
    required = {(feature.dimension, feature.name) for feature in features.features if feature.required}
    excluded = {(feature.dimension, feature.name) for feature in features.features if not feature.required}
    mapped_fields = {field for feature in features.features for field in feature.request_fields}

    def render(item: tuple[ClaimDimension, str]) -> str:
        return f"{item[0]}:{item[1]}"

    missing_endpoint_coverage = tuple(
        sorted(
            f"{feature.dimension}:{feature.name}@{endpoint}"
            for feature in features.features
            if feature.required
            for endpoint in feature.endpoints
            if not any(
                claim.dimension == feature.dimension
                and claim.name == feature.name
                and (not case.applies_to.endpoints or endpoint in case.applies_to.endpoints)
                for case in cases
                for claim in case.claims
            )
        )
    )

    return Coverage(
        covered=tuple(sorted(render(item) for item in claimed & required)),
        missing=tuple(sorted(render(item) for item in required - claimed)),
        missing_endpoint_coverage=missing_endpoint_coverage,
        excluded=tuple(sorted(render(item) for item in excluded)),
        unmapped_request_fields=tuple(sorted(set(Request.model_fields) - mapped_fields)),
        case_count=len(cases),
    )
