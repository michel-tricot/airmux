"""The command listing, which is the only place the whole CLI is visible at once."""

from __future__ import annotations

import json

from typer.testing import CliRunner

from cli.common import RESOURCES
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
    for path in ("airllm quickstart", "airllm orgs mine", "airllm provider-credentials add", "airllm access-keys mint"):
        assert path in paths

    assert "airllm bundles republish" in paths
    assert "airllm bundles compile" not in paths


def test_the_listing_does_not_list_itself():
    assert "airllm commands" not in [row["command"] for row in listed()]


def test_a_command_takes_its_category_from_its_group():
    """Most commands never name a category; the group they sit in is the answer."""
    rows = {row["command"]: row["category"] for row in listed()}

    assert rows["airllm orgs mine"] == RESOURCES
    assert rows["airllm workspaces create"] == RESOURCES
    assert rows["airllm users list"] == RESOURCES


def test_all_resource_commands_share_one_category():
    rows = {row["command"]: row["category"] for row in listed()}

    assert rows["airllm orgs list"] == RESOURCES
    assert rows["airllm orgs create"] == RESOURCES
    assert rows["airllm providers create"] == RESOURCES
    assert rows["airllm providers list"] == RESOURCES
    assert rows["airllm models create"] == RESOURCES
    assert rows["airllm models list"] == RESOURCES


def test_every_command_says_what_it_does():
    """A listing with blank rows is a listing nobody reads twice."""
    assert [row["command"] for row in listed() if not row["summary"]] == []


def test_the_table_groups_by_category():
    result = runner.invoke(app, ["commands"])

    assert result.exit_code == 0, result.output
    assert RESOURCES in result.stdout
