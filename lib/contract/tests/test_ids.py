from __future__ import annotations

import time
from uuid import UUID

from pydantic import BaseModel

from contract import uuid7


def test_uuid7_is_version_7_with_rfc_variant():
    value = uuid7()
    assert value.version == 7
    assert value.variant == "specified in RFC 4122"


def test_uuid7_embeds_the_current_time():
    before = time.time_ns() // 1_000_000
    embedded = uuid7().int >> 80
    after = time.time_ns() // 1_000_000
    assert before <= embedded <= after


def test_uuid7_sorts_by_creation_across_milliseconds():
    first = uuid7()
    time.sleep(0.002)
    second = uuid7()
    assert first < second


def test_uuid7_is_unique():
    values = {uuid7() for _ in range(1000)}
    assert len(values) == 1000


class IdentifiedValue(BaseModel):
    id: UUID


def test_uuid7_remains_a_standard_uuid_through_validation_and_json():
    value = uuid7()
    assert type(value) is UUID
    model = IdentifiedValue(id=value)
    assert model.id is value
    assert IdentifiedValue.model_validate_json(model.model_dump_json()).id == value
    assert UUID(bytes=value.bytes) == UUID(str(value)) == value


def test_rapid_uuid7_generation_does_not_advance_beyond_the_clock():
    before = time.time_ns() // 1_000_000
    values = [uuid7() for _ in range(10_000)]
    after = time.time_ns() // 1_000_000
    assert all(before <= value.int >> 80 <= after for value in values)
    assert len(set(values)) == len(values)
