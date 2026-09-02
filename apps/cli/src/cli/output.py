from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Annotated, NamedTuple

import typer
from pydantic import BaseModel
from rich import box
from rich.table import Table

from cli.common import console

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

RenderableRow = BaseModel | Mapping[str, object]


def _row_values(row: RenderableRow) -> Mapping[str, object]:
    return row.model_dump(mode="json") if isinstance(row, BaseModel) else row


class OutputFormat(StrEnum):
    table = "table"
    json = "json"
    text = "text"


FormatOption = Annotated[OutputFormat, typer.Option("--format", "-f", help="Output format: table, json or text.")]


def cell(value: object) -> str:
    if isinstance(value, list):
        return ", ".join(str(v) for v in value)
    if value is None:
        return ""
    return str(value)


def fmt_when(value: object) -> str:
    if not value:
        return ""
    return datetime.fromisoformat(str(value)).strftime("%Y-%m-%d %H:%M")


class Col(NamedTuple):
    key: str
    header: str
    style: str | None = None
    no_wrap: bool = False
    max_width: int | None = None
    fmt: Callable[[object], str] = cell


def build_table(rows: Sequence[RenderableRow], cols: Sequence[Col], row_style: Callable[[Mapping[str, object]], str | None] | None = None) -> Table:
    table = Table(box=box.ROUNDED, header_style="bold")
    for c in cols:
        table.add_column(c.header, style=c.style, no_wrap=c.no_wrap, max_width=c.max_width)
    for row in rows:
        values = _row_values(row)
        table.add_row(*(c.fmt(values.get(c.key)) for c in cols), style=row_style(values) if row_style else None)
    return table


def print_rows(name: str, rows: Sequence[RenderableRow], cols: Sequence[Col], fmt: OutputFormat) -> None:
    """Every command that outputs resource data renders through here; give it a FormatOption."""
    if fmt is OutputFormat.json:
        print(json.dumps([dict(_row_values(row)) for row in rows], indent=2, ensure_ascii=False))
        return
    if fmt is OutputFormat.text:
        for row in rows:
            values = _row_values(row)
            print("\t".join(c.fmt(values.get(c.key)) for c in cols))
        return
    if not rows:
        console.print(f"No {name} found.")
        return
    console.print(build_table(rows, cols))
