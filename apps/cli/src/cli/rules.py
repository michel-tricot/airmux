from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from pydantic import ValidationError

from api_models import DeletedOutUUID, RuleCreate, RuleOut, RuleUpdate
from cli.client import access_client, access_get, ensure_ok, org_path, payload, resolve_workspace
from cli.common import console, rules_app
from cli.output import Col, FormatOption, OutputFormat, print_rows

RuleFile = Annotated[Path, typer.Argument(exists=True, dir_okay=False, readable=True, help="JSON rule configuration")]
WorkspaceOption = Annotated[str, typer.Option("--workspace", "-w", help="Workspace slug or ID")]
RULE_COLS = [Col("id", "ID"), Col("name", "Name"), Col("definition", "Definition")]


@rules_app.command("list")
def list_rules(workspace: WorkspaceOption = "", control_plane_url: str = "", fmt: FormatOption = OutputFormat.table) -> None:
    """List reusable inference rules in the workspace."""
    rules = access_get(org_path(f"/workspaces/{resolve_workspace(workspace)}/rules"), control_plane_url, RuleOut)
    print_rows("rules", rules, RULE_COLS, fmt)


@rules_app.command("create")
def create_rule(
    configuration: RuleFile, workspace: WorkspaceOption = "", control_plane_url: str = "", fmt: FormatOption = OutputFormat.table
) -> None:
    """Create a reusable rule from JSON."""
    body = _configuration(configuration, RuleCreate)
    with access_client(control_plane_url) as client:
        response = ensure_ok(client.post(org_path(f"/workspaces/{resolve_workspace(workspace)}/rules"), json=body.model_dump(mode="json")))
    print_rows("rules", [payload(response, RuleOut)], RULE_COLS, fmt)


@rules_app.command("update")
def update_rule(
    rule_id: str,
    configuration: RuleFile,
    workspace: WorkspaceOption = "",
    control_plane_url: str = "",
    fmt: FormatOption = OutputFormat.table,
) -> None:
    """Update a reusable rule using a partial JSON configuration."""
    body = _configuration(configuration, RuleUpdate)
    with access_client(control_plane_url) as client:
        response = ensure_ok(
            client.patch(
                org_path(f"/workspaces/{resolve_workspace(workspace)}/rules/{rule_id}"), json=body.model_dump(mode="json", exclude_unset=True)
            )
        )
    print_rows("rules", [payload(response, RuleOut)], RULE_COLS, fmt)


@rules_app.command("delete")
def delete_rule(rule_id: str, workspace: WorkspaceOption = "", control_plane_url: str = "", fmt: FormatOption = OutputFormat.table) -> None:
    """Delete an unused workspace rule."""
    with access_client(control_plane_url) as client:
        response = ensure_ok(client.delete(org_path(f"/workspaces/{resolve_workspace(workspace)}/rules/{rule_id}")))
    print_rows("deleted rules", [payload(response, DeletedOutUUID)], [Col("id", "ID"), Col("deleted_at", "Deleted")], fmt)


def _configuration[T: RuleCreate | RuleUpdate](path: Path, model: type[T]) -> T:
    try:
        return model.model_validate_json(path.read_text())
    except (OSError, ValidationError) as error:
        console.print(f"Invalid rule configuration: {error}", markup=False)
        raise typer.Exit(1) from error
