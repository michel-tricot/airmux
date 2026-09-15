from __future__ import annotations

import typer

from cli.common import CONNECTION, GETTING_STARTED, RESOURCES, SERVICES, app, console
from cli.output import Col, FormatOption, OutputFormat, build_table, print_rows

COMMAND_COLS = [
    Col("command", "Command", style="bold", no_wrap=True),
    Col("category", "Category", style="dim", no_wrap=True),
    Col("summary", "What it does"),
]
"""The machine-readable shape: json and text carry the category on every row.

The table drops that column and uses the category as a heading instead, because three columns and a
sentence do not fit a terminal and rich answers that by wrapping every summary over six lines.
"""

TABLE_COLS = [Col("command", "Command", style="bold", no_wrap=True), Col("summary", "What it does")]

CATEGORY_ORDER = [GETTING_STARTED, CONNECTION, SERVICES, RESOURCES]
UNCATEGORISED = "Other"


def _category(command: object, inherited: str) -> str:
    """A command's own category, or its group's.

    Typer leaves an unset panel as a placeholder rather than None, so anything that is not a string
    means the command never chose one and takes the group's.
    """
    panel = getattr(command, "rich_help_panel", None)
    return panel if isinstance(panel, str) else inherited


def _summary(command: object) -> str:
    """The first line of the help, which is the sentence the command's own --help leads with."""
    text = str(getattr(command, "help", "") or "").strip()
    return text.split("\n", maxsplit=1)[0]


def walk(command: object, path: str, inherited: str) -> list[dict]:
    """Every leaf under a command, depth first, carrying the category down to it."""
    category = _category(command, inherited)
    children = getattr(command, "commands", None)
    if not children:
        return [{"command": path, "category": category, "summary": _summary(command)}]
    return [row for name, child in children.items() for row in walk(child, f"{path} {name}", category)]


def _sort_key(row: dict) -> tuple[int, str]:
    order = CATEGORY_ORDER.index(row["category"]) if row["category"] in CATEGORY_ORDER else len(CATEGORY_ORDER)
    return order, row["command"]


@app.command(rich_help_panel=GETTING_STARTED)
def commands(fmt: FormatOption = OutputFormat.table) -> None:
    """List every command in one place, instead of one --help at a time."""
    root = typer.main.get_command(app)
    found = [row for row in walk(root, "tokkeeper", UNCATEGORISED) if row["command"] != "tokkeeper commands"]
    rows = sorted(found, key=_sort_key)
    if fmt is not OutputFormat.table:
        print_rows("commands", rows, COMMAND_COLS, fmt)
        return
    for category in dict.fromkeys(row["category"] for row in rows):
        console.print(f"\n[bold]{category}[/bold]")
        console.print(build_table([row for row in rows if row["category"] == category], TABLE_COLS))
