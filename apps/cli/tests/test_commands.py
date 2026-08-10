"""The command listing, which is the only place the whole CLI is visible at once."""

from __future__ import annotations

import json

from typer.testing import CliRunner

from cli.common import ADMIN, ORG
from cli.main import app

runner = CliRunner()


def listed() -> list[dict]:
    result = runner.invoke(app, ["commands", "-f", "json"])
    assert result.exit_code == 0, result.output
    return json.loads(result.stdout)


def test_every_command_is_listed_once():
    """The point of the command: one place to look instead of a --help per group."""
    rows = listed()
    paths = [row["command"] for row in rows]

    assert len(paths) == len(set(paths))
    for path in ("airllm quickstart", "airllm orgs mine", "airllm provider-credentials add", "airllm instance-keys mint"):
        assert path in paths


def test_the_listing_does_not_list_itself():
    assert "airllm commands" not in [row["command"] for row in listed()]


def test_a_command_takes_its_category_from_its_group():
    """Most commands never name a category; the group they sit in is the answer."""
    rows = {row["command"]: row["category"] for row in listed()}

    assert rows["airllm orgs mine"] == ORG
    assert rows["airllm workspaces create"] == ORG
    assert rows["airllm users list"] == ADMIN


def test_a_command_can_override_its_group():
    """The mixed groups are why this listing is worth having: `orgs` is org scoped and two of its
    commands are not, which no amount of reading the top-level help would tell you."""
    rows = {row["command"]: row["category"] for row in listed()}

    assert rows["airllm orgs list"] == ADMIN
    assert rows["airllm orgs create"] == ADMIN
    assert rows["airllm providers create"] == ADMIN
    assert rows["airllm providers list"] == ORG
    assert rows["airllm models create"] == ADMIN
    assert rows["airllm models list"] == ORG


def test_every_command_says_what_it_does():
    """A listing with blank rows is a listing nobody reads twice."""
    assert [row["command"] for row in listed() if not row["summary"]] == []


def test_the_table_groups_by_category():
    result = runner.invoke(app, ["commands"])

    assert result.exit_code == 0, result.output
    assert ORG in result.stdout
    assert ADMIN in result.stdout
    assert result.stdout.index(ORG) < result.stdout.index(ADMIN)
