from __future__ import annotations


def emit(*values: object) -> None:
    print(*values)  # noqa: T201 catalog task output is captured and rendered by the Typer command boundary
