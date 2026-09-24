from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from pydantic import ValidationError

from api_models import DeletedOutUUID, PolicyBudgetStatus, PolicyCreate, PolicyOut, PolicyUpdate
from cli.client import access_client, access_get, ensure_ok, org_path, payload, resolve_workspace
from cli.common import console, policies_app
from cli.output import Col, FormatOption, OutputFormat, print_rows

PolicyFile = Annotated[Path, typer.Argument(exists=True, dir_okay=False, readable=True, help="JSON policy configuration")]
WorkspaceOption = Annotated[str, typer.Option("--workspace", "-w", help="Workspace slug or ID")]
POLICY_COLS = [Col("id", "ID"), Col("name", "Name"), Col("enabled", "Enabled"), Col("priority", "Priority"), Col("definition", "Definition")]


@policies_app.command("list")
def list_policies(workspace: WorkspaceOption = "", control_plane_url: str = "", fmt: FormatOption = OutputFormat.table) -> None:
    """List inference policies in the workspace."""
    policies = access_get(org_path(f"/workspaces/{resolve_workspace(workspace)}/policies"), control_plane_url, PolicyOut)
    print_rows("policies", policies, POLICY_COLS, fmt)


@policies_app.command("create")
def create_policy(
    configuration: PolicyFile, workspace: WorkspaceOption = "", control_plane_url: str = "", fmt: FormatOption = OutputFormat.table
) -> None:
    """Create a policy from JSON."""
    body = _configuration(configuration, PolicyCreate)
    with access_client(control_plane_url) as client:
        response = ensure_ok(
            client.post(org_path(f"/workspaces/{resolve_workspace(workspace)}/policies"), json=body.model_dump(mode="json", exclude_none=True))
        )
    print_rows("policies", [payload(response, PolicyOut)], POLICY_COLS, fmt)


@policies_app.command("update")
def update_policy(
    policy_id: str,
    configuration: PolicyFile,
    workspace: WorkspaceOption = "",
    control_plane_url: str = "",
    fmt: FormatOption = OutputFormat.table,
) -> None:
    """Update a policy using a partial JSON configuration."""
    body = _configuration(configuration, PolicyUpdate)
    with access_client(control_plane_url) as client:
        response = ensure_ok(
            client.patch(
                org_path(f"/workspaces/{resolve_workspace(workspace)}/policies/{policy_id}"), json=body.model_dump(mode="json", exclude_unset=True)
            )
        )
    print_rows("policies", [payload(response, PolicyOut)], POLICY_COLS, fmt)


@policies_app.command("delete")
def delete_policy(policy_id: str, workspace: WorkspaceOption = "", control_plane_url: str = "", fmt: FormatOption = OutputFormat.table) -> None:
    """Delete a workspace policy."""
    with access_client(control_plane_url) as client:
        response = ensure_ok(client.delete(org_path(f"/workspaces/{resolve_workspace(workspace)}/policies/{policy_id}")))
    print_rows("deleted policies", [payload(response, DeletedOutUUID)], [Col("id", "ID"), Col("deleted_at", "Deleted")], fmt)


def _configuration[T: PolicyCreate | PolicyUpdate](path: Path, model: type[T]) -> T:
    try:
        return model.model_validate_json(path.read_text())
    except (OSError, ValidationError) as error:
        console.print(f"Invalid policy configuration: {error}", markup=False)
        raise typer.Exit(1) from error


@policies_app.command("status")
def policy_status(  # noqa: PLR0913 CLI exposes independent filtering and output options
    policy_id: str,
    *,
    workspace: WorkspaceOption = "",
    rule_index: Annotated[int | None, typer.Option(min=0, max=99, help="Budget rule position, starting at zero")] = None,
    bucket_id: Annotated[str | None, typer.Option(help="Show spending for one budget bucket")] = None,
    after_bucket: Annotated[str | None, typer.Option(help="Continue after this budget bucket ID")] = None,
    limit: Annotated[int, typer.Option(min=1, max=1000)] = 100,
    control_plane_url: str = "",
    fmt: FormatOption = OutputFormat.table,
) -> None:
    """Show observed spending for each budget rule."""
    with access_client(control_plane_url) as client:
        response = ensure_ok(
            client.get(
                org_path(f"/workspaces/{resolve_workspace(workspace)}/policies/{policy_id}/status"),
                params={
                    name: value
                    for name, value in {"rule_index": rule_index, "bucket_id": bucket_id, "after_bucket": after_bucket, "limit": limit}.items()
                    if value is not None
                },
            )
        )
    status = payload(response, PolicyBudgetStatus)
    budgets = [{**budget.model_dump(mode="json"), "computed_at": status.computed_at.isoformat()} for budget in status.budgets]
    print_rows(
        "budget status",
        budgets,
        [
            Col("rule_index", "Rule"),
            Col("period", "Period"),
            Col("aggregation", "Aggregation"),
            Col("amount_usd", "Limit USD"),
            Col("buckets", "Bucket spending"),
            Col("window_end", "Resets"),
            Col("computed_at", "Calculated"),
            Col("next_bucket", "Next bucket"),
        ],
        fmt,
    )
