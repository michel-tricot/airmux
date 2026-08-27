from __future__ import annotations

import json
from enum import StrEnum
from typing import TYPE_CHECKING, Annotated, NamedTuple

import typer
from rich.console import Console
from rich.table import Table
from rich.text import Text

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


STATUS_STYLES = {
    "✓ supported": "bold green",
    "✓ match": "bold green",
    "✓ completed": "bold green",
    "covered": "green",
    "none": "dim green",
    "○ unsupported": "yellow",
    "? unknown": "yellow",
    "? inconclusive": "yellow",
    "? access blocked": "yellow",
    "excluded": "yellow",
    "inconclusive": "yellow",
    "✗ mismatch": "bold red",
    "✗ harness error": "bold red",
    "missing": "bold red",
    "missing endpoint": "bold red",
    "unmapped": "bold red",
    "harness": "bold red",
    "gateway_rejection": "bold red",
    "semantic": "bold red",
    "error_mapping": "bold red",
    "streaming": "bold red",
    "translation": "bold red",
}


def table_cell(value: object) -> Text:
    text = str(value)
    return Text(text, style=STATUS_STYLES.get(text, ""))


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
        table.add_column(column.header, overflow="fold")
    for row in rows:
        table.add_row(*(table_cell(row.get(column.key, "")) for column in columns))
    Console().print(table)
