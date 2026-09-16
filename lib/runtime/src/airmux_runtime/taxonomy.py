from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING

import yaml
from yaml.constructor import ConstructorError
from yaml.nodes import MappingNode, ScalarNode

from contract.money import fixed_point, parse_fixed_point
from contract.taxonomy import TaxonomySpec

if TYPE_CHECKING:
    from pathlib import Path

_MONEY_FIELDS = frozenset(
    {
        "input_price_per_mtok",
        "output_price_per_mtok",
        "cache_read_price_per_mtok",
        "cache_write_price_per_mtok",
    }
)


class _TaxonomyLoader(yaml.SafeLoader):
    def construct_mapping(self, node: MappingNode, deep: bool = False) -> dict[object, object]:
        self.flatten_mapping(node)
        mapping = {}
        for key_node, value_node in node.value:
            key = self.construct_object(key_node, deep=deep)
            if key in _MONEY_FIELDS:
                if not isinstance(value_node, ScalarNode):
                    raise ConstructorError(None, None, "money must be a scalar", value_node.start_mark)
                try:
                    value = parse_fixed_point(value_node.value)
                except ValueError as error:
                    raise ConstructorError(None, None, str(error), value_node.start_mark) from error
            else:
                value = self.construct_object(value_node, deep=deep)
            mapping[key] = value
        return mapping


class _TaxonomyDumper(yaml.SafeDumper):
    pass


def _represent_decimal(dumper: _TaxonomyDumper, value: Decimal) -> yaml.Node:
    rendered = fixed_point(value)
    tag = "tag:yaml.org,2002:float" if "." in rendered else "tag:yaml.org,2002:int"
    return dumper.represent_scalar(tag, rendered)


_TaxonomyDumper.add_representer(Decimal, _represent_decimal)


def load_taxonomy_document(text: str) -> object:
    return yaml.load(text, Loader=_TaxonomyLoader) or {}  # noqa: S506 Taxonomy loader subclasses SafeLoader


def parse_taxonomy(path: Path) -> TaxonomySpec:
    return load_taxonomy(path.read_text(encoding="utf-8"))


def load_taxonomy(text: str) -> TaxonomySpec:
    return TaxonomySpec.model_validate(load_taxonomy_document(text))


def dump_taxonomy(specification: object) -> str:
    return yaml.dump(specification, Dumper=_TaxonomyDumper, sort_keys=False, width=200, allow_unicode=True)
