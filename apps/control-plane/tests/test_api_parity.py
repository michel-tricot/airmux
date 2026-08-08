from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from sqlalchemy import inspect

import control_plane.app  # noqa: F401 imports every route module so the marker subclass walks below see all api models
from control_plane.models.common.base import Record, api_dispositions, api_set
from control_plane.models.common.wire import RecordCreate, RecordOut, RecordUpdate

if TYPE_CHECKING:
    from pydantic import BaseModel

DISPOSITION_NAMES = ("api_hidden", "api_readonly", "api_immutable")


def _subclasses[T](cls: type[T]) -> set[type[T]]:
    return {sub for child in cls.__subclasses__() for sub in (child, *_subclasses(child))}


TABLES = {cls.__name__: cls for cls in _subclasses(Record) if hasattr(cls, "__table__")}


def _declared_table(cls: type[BaseModel], marker: type[BaseModel]) -> type[Record] | None:
    """The type argument of the marker base: RecordOut[Org] -> Org; pydantic keeps it in the generic metadata."""
    metadata = (getattr(base, "__pydantic_generic_metadata__", None) for base in cls.__mro__)
    arg = next((meta["args"][0] for meta in metadata if meta and meta["origin"] is marker and meta["args"]), None)
    return arg if isinstance(arg, type) and issubclass(arg, Record) and hasattr(arg, "__table__") else None


def _paired(marker: type[BaseModel]) -> tuple[dict[type[Record], list[type[BaseModel]]], list[str]]:
    """Group every marker subclass under the table it is parametrized with; the type argument is the pairing, never the name."""
    pairs: dict[type[Record], list[type[BaseModel]]] = {}
    problems: list[str] = []
    for cls in sorted(_subclasses(marker), key=lambda c: c.__name__):
        if cls.__pydantic_generic_metadata__["origin"] is marker:
            continue
        table = _declared_table(cls, marker)
        if table is None:
            problems.append(f"{cls.__name__} does not declare its table: subclass {marker.__name__}[SomeTable], not bare {marker.__name__}.")
        else:
            pairs.setdefault(table, []).append(cls)
    return pairs, problems


def _single(pairs: dict[type[Record], list[type[BaseModel]]], marker_name: str) -> tuple[dict[type[Record], type[BaseModel]], list[str]]:
    """Create and Update stay one per table; only Outs may have summary variants."""
    problems = [
        f"{table.__name__} has {len(models)} {marker_name} models ({', '.join(m.__name__ for m in models)}): one table, one input shape."
        for table, models in pairs.items()
        if len(models) > 1
    ]
    return {table: models[0] for table, models in pairs.items()}, problems


OUTS, OUT_PROBLEMS = _paired(RecordOut)
_CREATE_GROUPS, _CREATE_GROUP_PROBLEMS = _paired(RecordCreate)
_UPDATE_GROUPS, _UPDATE_GROUP_PROBLEMS = _paired(RecordUpdate)
CREATES, _CREATE_SINGLE_PROBLEMS = _single(_CREATE_GROUPS, "RecordCreate")
UPDATES, _UPDATE_SINGLE_PROBLEMS = _single(_UPDATE_GROUPS, "RecordUpdate")
CREATE_PROBLEMS = _CREATE_GROUP_PROBLEMS + _CREATE_SINGLE_PROBLEMS
UPDATE_PROBLEMS = _UPDATE_GROUP_PROBLEMS + _UPDATE_SINGLE_PROBLEMS


def _cases(pairs) -> pytest.MarkDecorator:
    items = sorted(pairs.items(), key=lambda item: item[0].__name__)
    return pytest.mark.parametrize("table", [table for table, _ in items], ids=[table.__name__ for table, _ in items])


tables = pytest.mark.parametrize("table", [TABLES[name] for name in sorted(TABLES)], ids=sorted(TABLES))


def _report(problems: list[str]) -> str:
    return "\n".join(problems)


def test_every_api_model_declares_its_table():
    assert OUT_PROBLEMS + CREATE_PROBLEMS + UPDATE_PROBLEMS == [], _report(OUT_PROBLEMS + CREATE_PROBLEMS + UPDATE_PROBLEMS)


@tables
def test_disposition_names_exist_on_the_table(table: type[Record]):
    """A typo in an api_* set would silently protect nothing; every declared name must be a real column."""
    problems = [
        f"{table.__name__}.{name} names columns that do not exist: {sorted(unknown)}. Fix the typo or drop the entry."
        for name in DISPOSITION_NAMES
        if (unknown := api_set(table, name) - set(table.model_fields))
    ]
    assert problems == [], _report(problems)


@_cases(CREATES | UPDATES)
def test_primary_keys_are_never_writable(table: type[Record]):
    """A writable or patchable primary key would let callers rename rows; tables with inputs must place the pk in a frozen disposition."""
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


@_cases(OUTS)
def test_outs_stay_within_the_table_and_one_mirrors_it_fully(table: type[Record]):
    """Every Out is a subset of the public columns plus its own api_extra (a summary can narrow, never leak),
    and exactly one Out per table is the full mirror, so a forgotten column always fails somewhere."""
    hidden, _, _ = api_dispositions(table)
    public = set(table.model_fields) - hidden
    problems: list[str] = []
    mirrors: list[str] = []
    for out in OUTS[table]:
        extra = api_set(out, "api_extra")
        if bad := sorted(extra & set(table.model_fields)):
            problems.append(f"{out.__name__}.api_extra names table columns {bad}; api_extra is only for computed response fields.")
        fields = set(out.model_fields)
        if leaked := sorted(fields - public - extra):
            problems.append(
                f"{out.__name__} exposes {leaked}, which are hidden or not columns; an Out stays within the public columns plus its api_extra."
            )
        problems.extend(
            f"{out.__name__}.{name} is annotated {out.model_fields[name].annotation} but {table.__name__}.{name} is "
            f"{table.model_fields[name].annotation}. Annotations must match the table exactly."
            for name in sorted(fields & public)
            if out.model_fields[name].annotation != table.model_fields[name].annotation
        )
        if fields == public | extra:
            mirrors.append(out.__name__)
    if len(mirrors) != 1:
        others = ", ".join(mirrors) if mirrors else "none"
        problems.append(
            f"{table.__name__} needs exactly one full Out mirror carrying every public column (found: {others}); "
            f"summaries must drop at least one public column."
        )
    assert problems == [], _report(problems)


@_cases(CREATES)
def test_create_accepts_exactly_the_writable_fields(table: type[Record]):
    create = CREATES[table]
    hidden, readonly, _ = api_dispositions(table)
    problems = _field_sync(
        table,
        create,
        set(table.model_fields) - hidden - readonly,
        f"A caller-settable column belongs in {create.__name__}; a server-owned column belongs in {table.__name__}.api_readonly.",
    )
    assert problems == [], _report(problems)


@_cases(UPDATES)
def test_update_is_the_optional_mutable_subset(table: type[Record]):
    update = UPDATES[table]
    hidden, readonly, immutable = api_dispositions(table)
    expected = set(table.model_fields) - hidden - readonly - immutable
    problems = []
    if missing := sorted(expected - set(update.model_fields)):
        problems.append(
            f"{update.__name__} is missing fields {missing}. A mutable column belongs in {update.__name__} as `field: T | None = None`; "
            f"a create-only column belongs in {table.__name__}.api_immutable."
        )
    if unexpected := sorted(set(update.model_fields) - expected):
        problems.append(f"{update.__name__} has unexpected fields {unexpected}; hidden, readonly, and immutable columns are not patchable.")
    for name in sorted(expected & set(update.model_fields)):
        field = update.model_fields[name]
        expected_annotation = table.model_fields[name].annotation | None
        if field.annotation != expected_annotation or field.is_required() or field.default is not None:
            problems.append(
                f"{update.__name__}.{name} must be declared `{name}: {expected_annotation} = None` so PATCH can distinguish "
                f"omitted from explicitly-null; got {field.annotation} with default {field.default!r}."
            )
    assert problems == [], _report(problems)
