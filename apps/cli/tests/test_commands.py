"""The command listing, which is the only place the whole CLI is visible at once."""

from __future__ import annotations

import json

from typer.testing import CliRunner

from cli.common import GOODIES, RESOURCES
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
    for path in (
        "airmux quickstart",
        "airmux status",
        "airmux doctor",
        "airmux profiles list",
        "airmux profiles use",
        "airmux orgs mine",
        "airmux provider-credentials add",
        "airmux provider-credentials enable",
        "airmux provider-credentials disable",
        "airmux management-keys create",
        "airmux catalog apply",
        "airmux gateways list",
    ):
        assert path in paths


def test_the_listing_does_not_list_itself():
    assert "airmux commands" not in [row["command"] for row in listed()]


def test_a_command_takes_its_category_from_its_group():
    """Most commands never name a category; the group they sit in is the answer."""
    rows = {row["command"]: row["category"] for row in listed()}

    assert rows["airmux orgs mine"] == RESOURCES
    assert rows["airmux workspaces create"] == RESOURCES
    assert rows["airmux users list"] == RESOURCES


def test_all_resource_commands_share_one_category():
    rows = {row["command"]: row["category"] for row in listed()}

    assert rows["airmux orgs list"] == RESOURCES
    assert rows["airmux orgs create"] == RESOURCES
    assert rows["airmux providers list"] == RESOURCES
    assert rows["airmux models list"] == RESOURCES


def test_every_command_says_what_it_does():
    """A listing with blank rows is a listing nobody reads twice."""
    assert [row["command"] for row in listed() if not row["summary"]] == []


def test_the_table_groups_by_category():
    result = runner.invoke(app, ["commands"])

    assert result.exit_code == 0, result.output
    assert RESOURCES in result.stdout


def test_categories_follow_the_user_task():
    categories = {command["command"]: command["category"] for command in listed()}

    assert categories["airmux quickstart"] == "Getting started"
    for command in ("login", "profiles list", "status", "doctor"):
        assert categories[f"airmux {command}"] == "Connection"
    for command in ("gateway init", "gateway serve", "control-plane init", "control-plane serve"):
        assert categories[f"airmux {command}"] == "Services"
    for command in ("catalog apply", "gateways list", "orgs list"):
        assert categories[f"airmux {command}"] == "Manage resources"
    assert categories["airmux completion"] == GOODIES

    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    headings = ("Getting started", "Connection", GOODIES, "Services", "Manage resources")
    positions = [result.stdout.index(heading) for heading in headings]
    assert positions == sorted(positions)


def test_completion_installs_for_the_selected_shell(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))

    result = runner.invoke(app, ["completion", "--shell", "fish"])

    assert result.exit_code == 0, result.output
    completion = tmp_path / ".config/fish/completions/airmux.fish"
    assert completion.is_file()
    assert "airmux" in completion.read_text()
    assert f"Installed fish completion at {completion}" in result.output
