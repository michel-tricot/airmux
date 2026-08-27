from __future__ import annotations

import json
from enum import StrEnum
from typing import TYPE_CHECKING, Annotated, NamedTuple

import typer
from rich.console import Console
from rich.table import Table

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence


class OutputFormat(StrEnum):
    table = "table"
    json = "json"
    text = "text"


FormatOption = Annotated[OutputFormat, typer.Option("--format", "-f", help="Output format: table, json or text")]


class Col(NamedTuple):
    key: str
    header: str


def print_rows(name: str, rows: Sequence[Mapping[str, object]], columns: Sequence[Col], output_format: OutputFormat) -> None:
    if output_format is OutputFormat.json:
        typer.echo(json.dumps(rows, indent=2, ensure_ascii=False))
        return
    if output_format is OutputFormat.text:
        for row in rows:
            typer.echo("\t".join(str(row.get(column.key, "")) for column in columns))
        return
    if not rows:
        Console().print(f"No {name} found")
        return
    table = Table()
    for column in columns:
        table.add_column(column.header)
    for row in rows:
        table.add_row(*(str(row.get(column.key, "")) for column in columns))
    Console().print(table)
