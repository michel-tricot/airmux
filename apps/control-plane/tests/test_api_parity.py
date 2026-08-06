from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from sqlalchemy import inspect

import control_plane.app  # noqa: F401 imports every route module so the marker subclass walks below see all api models
from control_plane.models.base import Record
from control_plane.schemas import ApiCreate, ApiOut, ApiPatch, api_dispositions, api_set

if TYPE_CHECKING:
    from pydantic import BaseModel

DISPOSITION_NAMES = ("api_hidden", "api_readonly", "api_immutable")


def _subclasses[T](cls: type[T]) -> set[type[T]]:
    return {sub for child in cls.__subclasses__() for sub in (child, *_subclasses(child))}


TABLES = {cls.__name__: cls for cls in _subclasses(Record) if hasattr(cls, "__table__")}


def _paired(marker: type[BaseModel], suffix: str) -> tuple[dict[type[Record], type[BaseModel]], list[str]]:
    """Pair every marker subclass to its table by name: <Table><suffix> -> <Table>."""
    pairs: dict[type[Record], type[BaseModel]] = {}
    problems: list[str] = []
    for cls in sorted(_subclasses(marker), key=lambda c: c.__name__):
        table = TABLES.get(cls.__name__.removesuffix(suffix))
        if not cls.__name__.endswith(suffix) or table is None:
            problems.append(
                f"{cls.__name__} subclasses {marker.__name__} but does not pair with a table: name it <Table>{suffix} "
                f"for one of {sorted(TABLES)}, or make it a plain BaseModel if it is an action body."
            )
        else:
            pairs[table] = cls
    return pairs, problems


OUTS, OUT_PROBLEMS = _paired(ApiOut, "Out")
CREATES, CREATE_PROBLEMS = _paired(ApiCreate, "Create")
PATCHES, PATCH_PROBLEMS = _paired(ApiPatch, "Patch")

tables = pytest.mark.parametrize("table", [TABLES[name] for name in sorted(TABLES)], ids=sorted(TABLES))


def _report(problems: list[str]) -> str:
    return "\n".join(problems)


def test_every_api_model_pairs_with_a_table():
    assert OUT_PROBLEMS + CREATE_PROBLEMS + PATCH_PROBLEMS == [], _report(OUT_PROBLEMS + CREATE_PROBLEMS + PATCH_PROBLEMS)


@tables
def test_disposition_names_exist_on_the_table(table: type[Record]):
    """A typo in an api_* set would silently protect nothing; every declared name must be a real column."""
    problems = [
        f"{table.__name__}.{name} names columns that do not exist: {sorted(unknown)}. Fix the typo or drop the entry."
        for name in DISPOSITION_NAMES
        if (unknown := api_set(table, name) - set(table.model_fields))
    ]
    assert problems == [], _report(problems)


@tables
def test_primary_keys_are_never_writable(table: type[Record]):
    """A writable or patchable primary key would let callers rename rows; tables with inputs must place the pk in a frozen disposition."""
    if table not in CREATES and table not in PATCHES:
        pytest.skip("table has no input models, so callers cannot send an id")
    hidden, readonly, immutable = api_dispositions(table)
    mapper = inspect(table, raiseerr=False)
    assert mapper is not None
    pk_columns = {column.name for column in mapper.primary_key}
    problems = [
        f"{table.__name__}.{name} is a primary key but is neither api_readonly (server-minted) nor api_immutable (caller-chosen, frozen "
        f"after create). Declare one so the id cannot be changed through the API."
        for name in sorted(pk_columns - hidden - readonly - immutable)
    ]
    assert problems == [], _report(problems)


def _field_sync(table: type[Record], kind: type[BaseModel], expected: set[str], fixes: str) -> list[str]:
    problems = []
    if missing := sorted(expected - set(kind.model_fields)):
        problems.append(f"{kind.__name__} is missing fields {missing}. {fixes}")
    if unexpected := sorted(set(kind.model_fields) - expected):
        problems.append(f"{kind.__name__} has unexpected fields {unexpected}. {fixes}")
    problems.extend(
        f"{kind.__name__}.{name} is annotated {kind.model_fields[name].annotation} but {table.__name__}.{name} is "
        f"{table.model_fields[name].annotation}. Annotations must match the table exactly."
        for name in sorted(expected & set(kind.model_fields) & set(table.model_fields))
        if kind.model_fields[name].annotation != table.model_fields[name].annotation
    )
    return problems


@tables
def test_out_mirrors_the_table_minus_hidden(table: type[Record]):
    out = OUTS.get(table)
    if out is None:
        pytest.skip("table has no Out model")
    hidden, _, _ = api_dispositions(table)
    extra = api_set(out, "api_extra")
    problems = (
        [f"{out.__name__}.api_extra names table columns {sorted(extra & set(table.model_fields))}; api_extra is only for computed response fields."]
        if extra & set(table.model_fields)
        else []
    )
    problems += _field_sync(
        table,
        out,
        (set(table.model_fields) - hidden) | extra,
        f"A public column belongs in {out.__name__}; a column that must never cross the wire belongs in {table.__name__}.api_hidden; "
        f"a computed response field belongs in {out.__name__}.api_extra.",
    )
    assert problems == [], _report(problems)


@tables
def test_create_accepts_exactly_the_writable_fields(table: type[Record]):
    create = CREATES.get(table)
    if create is None:
        pytest.skip("table has no Create model")
    hidden, readonly, _ = api_dispositions(table)
    problems = _field_sync(
        table,
        create,
        set(table.model_fields) - hidden - readonly,
        f"A caller-settable column belongs in {create.__name__}; a server-owned column belongs in {table.__name__}.api_readonly.",
    )
    assert problems == [], _report(problems)


@tables
def test_patch_is_the_optional_mutable_subset(table: type[Record]):
    patch = PATCHES.get(table)
    if patch is None:
        pytest.skip("table has no Patch model")
    hidden, readonly, immutable = api_dispositions(table)
    expected = set(table.model_fields) - hidden - readonly - immutable
    problems = []
    if missing := sorted(expected - set(patch.model_fields)):
        problems.append(
            f"{patch.__name__} is missing fields {missing}. A mutable column belongs in {patch.__name__} as `field: T | None = None`; "
            f"a create-only column belongs in {table.__name__}.api_immutable."
        )
    if unexpected := sorted(set(patch.model_fields) - expected):
        problems.append(f"{patch.__name__} has unexpected fields {unexpected}; hidden, readonly, and immutable columns are not patchable.")
    for name in sorted(expected & set(patch.model_fields)):
        field = patch.model_fields[name]
        expected_annotation = table.model_fields[name].annotation | None
        if field.annotation != expected_annotation or field.is_required() or field.default is not None:
            problems.append(
                f"{patch.__name__}.{name} must be declared `{name}: {expected_annotation} = None` so PATCH can distinguish "
                f"omitted from explicitly-null; got {field.annotation} with default {field.default!r}."
            )
    assert problems == [], _report(problems)
