from __future__ import annotations

import pytest
from tests.acceptance.gateway.gateway_sharding import Shard, shard_for


def test_collected_node_ids_land_in_exactly_one_shard():
    node_ids = [f"tests/acceptance/gateway/test_example.py::test_case[{index}]" for index in range(100)]
    assignments = {node_id: [index for index in range(4) if shard_for(node_id, 4) == index] for node_id in node_ids}
    assert all(len(indices) == 1 for indices in assignments.values())
    assert {indices[0] for indices in assignments.values()} == {0, 1, 2, 3}


@pytest.mark.parametrize("value", ["", "0", "0/0", "-1/4", "4/4", "one/4", "0/four"])
def test_invalid_shards_are_rejected(value: str):
    with pytest.raises(ValueError, match="shard"):
        Shard.parse(value)


def test_shard_parser_preserves_the_requested_partition():
    assert Shard.parse("2/4") == Shard(index=2, total=4)
