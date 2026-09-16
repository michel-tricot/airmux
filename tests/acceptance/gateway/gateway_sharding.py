from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

import pytest


class InvalidShardError(ValueError):
    def __init__(self, value: str) -> None:
        super().__init__(f"invalid shard: {value}")


@dataclass(frozen=True)
class Shard:
    index: int
    total: int

    @classmethod
    def parse(cls, value: str) -> Shard:
        match = re.fullmatch(r"([0-9]+)/([1-9][0-9]*)", value)
        if match is None:
            raise InvalidShardError(value)
        shard = cls(index=int(match.group(1)), total=int(match.group(2)))
        if shard.index >= shard.total:
            raise InvalidShardError(value)
        return shard


def shard_for(node_id: str, total: int) -> int:
    digest = hashlib.sha256(node_id.encode()).digest()
    return int.from_bytes(digest[:8]) % total


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption("--shard")


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    value = config.getoption("shard")
    if value is None:
        return
    try:
        shard = Shard.parse(value)
    except ValueError as error:
        raise pytest.UsageError(str(error)) from error
    selected = [item for item in items if shard_for(item.nodeid, shard.total) == shard.index]
    deselected = [item for item in items if shard_for(item.nodeid, shard.total) != shard.index]
    config.hook.pytest_deselected(items=deselected)
    items[:] = selected
