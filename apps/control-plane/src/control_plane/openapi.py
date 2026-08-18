from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import FastAPI
from fastapi.routing import APIRoute

from control_plane.sessions import SESSION_COOKIE

if TYPE_CHECKING:
    from typing import Any

API_DESCRIPTION = """Manage AirLLM organizations, workspaces, access keys, provider credentials, and data-plane synchronization.

Organization and workspace targets are part of each URL. Successful responses wrap their result in
`{"data": ...}`. Authenticate with a control-plane access key or a browser session as documented by
each operation. Inference keys authenticate model requests at the data plane and are not accepted here.
"""

API_TAGS = [
    {
        "name": "Auth",
        "x-displayName": "Authentication",
        "description": "Sign in human users, manage browser sessions, and authorize the CLI",
    },
    {"name": "Enrollment", "description": "List a user's organizations and create their personal organization"},
    {
        "name": "Instance Organizations",
        "x-displayName": "Organizations",
        "description": "List and create organizations on this AirLLM instance",
    },
    {"name": "Instance Users", "x-displayName": "Users", "description": "Manage human users and service accounts across the instance"},
    {
        "name": "Instance Access Keys",
        "x-displayName": "Access Keys",
        "description": "List access keys across the instance, issue instance-scoped credentials, and revoke keys",
    },
    {
        "name": "Instance Model Catalog",
        "x-displayName": "Model Catalog",
        "description": "Manage the providers and models available through this AirLLM instance",
    },
    {"name": "Data Plane Instances", "x-displayName": "Data Planes", "description": "Inspect connected data-plane instances"},
    {"name": "Instance Activity", "x-displayName": "Activity", "description": "Inspect recent audited changes across the instance"},
    {"name": "OSS", "x-displayName": "Self-hosting", "description": "Bootstrap a new self-hosted AirLLM deployment"},
    {"name": "Organization Settings", "x-displayName": "Settings", "description": "View, update, and delete one organization"},
    {
        "name": "Organization Members",
        "x-displayName": "Members",
        "description": "Manage organization membership and organization roles",
    },
    {
        "name": "Organization Invitations",
        "x-displayName": "Invitations",
        "description": "Invite human users to an organization and optionally one workspace",
    },
    {
        "name": "Organization Workspaces",
        "x-displayName": "Workspaces",
        "description": "List and create workspaces within an organization",
    },
    {
        "name": "Organization Access Keys",
        "x-displayName": "Access Keys",
        "description": "List access keys within an organization, issue organization-scoped credentials, and revoke keys",
    },
    {
        "name": "Organization Provider Credentials",
        "x-displayName": "Provider Credentials",
        "description": "Manage provider API keys available across an organization",
    },
    {"name": "Organization Bundles", "x-displayName": "Bundles", "description": "Compile and inspect signed policy bundles"},
    {
        "name": "Organization Usage Events",
        "x-displayName": "Usage Events",
        "description": "Inspect usage events across an organization",
    },
    {"name": "Organization Activity", "x-displayName": "Activity", "description": "Inspect recent audited changes in an organization"},
    {
        "name": "Organization Model Catalog",
        "x-displayName": "Model Catalog",
        "description": "Inspect the provider and model catalog available to an organization",
    },
    {"name": "Workspace Settings", "x-displayName": "Settings", "description": "View, update, and delete one workspace"},
    {
        "name": "Workspace Members",
        "x-displayName": "Members",
        "description": "Manage workspace membership and workspace roles",
    },
    {
        "name": "Workspace Access Keys",
        "x-displayName": "Access Keys",
        "description": "List and issue access keys scoped to a workspace and revoke keys",
    },
    {
        "name": "Workspace Inference Keys",
        "x-displayName": "Inference Keys",
        "description": "Issue and revoke credentials for model requests to a workspace",
    },
    {
        "name": "Workspace Provider Credentials",
        "x-displayName": "Provider Credentials",
        "description": "Manage provider API keys available to one workspace",
    },
    {
        "name": "Workspace Usage Events",
        "x-displayName": "Usage Events",
        "description": "Inspect usage events for one workspace",
    },
    {
        "name": "Workspace Model Catalog",
        "x-displayName": "Model Catalog",
        "description": "Inspect the provider and model catalog available to a workspace",
    },
    {
        "name": "Data Plane API",
        "x-displayName": "Synchronization",
        "description": "Poll bundles, ingest usage events, and record data-plane heartbeats",
    },
]

TAG_GROUPS = [
    {"name": "Account", "tags": ["Auth", "Enrollment"]},
    {
        "name": "Instance",
        "tags": [
            "Instance Organizations",
            "Instance Users",
            "Instance Access Keys",
            "Instance Model Catalog",
            "Data Plane Instances",
            "Instance Activity",
            "OSS",
        ],
    },
    {
        "name": "Organization",
        "tags": [
            "Organization Settings",
            "Organization Members",
            "Organization Invitations",
            "Organization Workspaces",
            "Organization Access Keys",
            "Organization Provider Credentials",
            "Organization Bundles",
            "Organization Usage Events",
            "Organization Activity",
            "Organization Model Catalog",
        ],
    },
    {
        "name": "Workspace",
        "tags": [
            "Workspace Settings",
            "Workspace Members",
            "Workspace Access Keys",
            "Workspace Inference Keys",
            "Workspace Provider Credentials",
            "Workspace Usage Events",
            "Workspace Model Catalog",
        ],
    },
    {"name": "Data Plane API", "tags": ["Data Plane API"]},
]

OPERATION_SUMMARIES = {
    "signup": "Sign Up",
    "me": "Get Current User",
    "my_permissions": "Get Effective Permissions",
    "cli_auth_start": "Start CLI Authorization",
    "cli_auth_request_details": "Get CLI Authorization Request",
    "cli_auth_approve": "Approve CLI Authorization",
    "cli_auth_poll": "Poll CLI Authorization",
    "enrollment": "Get Current Enrollment",
    "create_personal_org": "Create Personal Organization",
    "preview_invitation": "Preview Invitation",
    "accept_invitation": "Accept Invitation",
    "claim": "Get Instance Claim Status",
    "quickstart": "Install First Data Plane Credential",
    "list_orgs": "List Organizations",
    "create_org": "Create Organization",
    "update_org": "Update Organization",
    "get_org": "Get Organization",
    "delete_org": "Delete Organization",
    "list_org_users": "List Organization Members",
    "add_org_user": "Add Organization Member",
    "remove_org_user": "Remove Organization Member",
    "create_invitation": "Create Organization Invitation",
    "list_invitations": "List Organization Invitations",
    "reissue_invitation": "Reissue Organization Invitation",
    "revoke_invitation": "Revoke Organization Invitation",
    "list_members": "List Workspace Members",
    "list_member_candidates": "List Workspace Member Candidates",
    "add_member": "Add Workspace Member",
    "remove_member": "Remove Workspace Member",
    "compile_bundle": "Compile Policy Bundle",
    "list_activity": "List Organization Activity",
    "bundle_latest": "Get Latest Bundle",
    "ingest_events": "Ingest Usage Events",
    "heartbeat": "Record Data Plane Heartbeat",
    "get_instance_taxonomy": "Get Instance Model Catalog",
    "get_org_taxonomy": "Get Organization Model Catalog",
    "get_workspace_taxonomy": "Get Workspace Model Catalog",
    "create_provider": "Create or Update Provider",
    "create_model": "Create or Update Model",
}

PARAMETER_DESCRIPTIONS = {
    "org_id": "Organization ID",
    "workspace_ref": "Workspace ID or slug",
    "user_id": "User or service-account ID",
    "invitation_id": "Organization invitation ID",
    "credential_id": "Provider credential ID",
    "code": "Device authorization code shown by the CLI",
    "include_offline": "Include data planes whose most recent heartbeat is outside the online window",
    "service_account": "Filter by principal type: true for service accounts and false for human users",
    "limit": "Maximum number of results to return",
    "before": "Return events before this timestamp; use with before_event_id",
    "before_event_id": "Event ID that disambiguates the before timestamp",
    "after": "Return events after this timestamp; use with after_event_id",
    "after_event_id": "Event ID that disambiguates the after timestamp",
}


def _parameter_description(path: str, name: str, location: str) -> str:
    if name == "key_id":
        return "Inference key ID" if "inference-keys" in path else "Access key ID"
    if name == "user_id" and location == "query":
        return "Return only access keys issued to this principal"
    if name == "org_id" and location == "query":
        if "auth/permissions" in path:
            return "Organization scope to evaluate; omit for instance scope"
        return "Organization whose latest bundle to return; omit to use the credential's scope"
    if name == "workspace_ref" and location == "query" and "auth/permissions" in path:
        return "Workspace ID or slug to evaluate within org_id; omit for organization scope"
    return PARAMETER_DESCRIPTIONS.get(name, name.replace("_", " ").capitalize())


def _api_routes(routes: list[Any]) -> list[APIRoute]:
    routers = (getattr(route, "original_router", None) for route in routes)
    nested = [route for router in routers if router is not None for route in _api_routes(router.routes)]
    return [*(route for route in routes if isinstance(route, APIRoute)), *nested]


class ControlPlaneApp(FastAPI):
    def openapi(self) -> dict[str, Any]:
        if self.openapi_schema:
            return self.openapi_schema
        schema = super().openapi()
        schema["x-tagGroups"] = TAG_GROUPS
        security_schemes = schema.setdefault("components", {}).setdefault("securitySchemes", {})
        security_schemes["SessionCookie"] = {
            "type": "apiKey",
            "in": "cookie",
            "name": SESSION_COOKIE,
            "description": "Browser session cookie returned by login or signup. Browser requests must also send `X-Requested-With`.",
        }
        for route in _api_routes(self.routes):
            permissions = [
                str(permission)
                for dependency in route.dependant.dependencies
                if (permission := getattr(dependency.call, "required_permission", None))
            ]
            access = [kind for dependency in route.dependant.dependencies if (kind := getattr(dependency.call, "access", None)) is not None]
            for method in route.methods or ():
                path = "/api/v1" + route.path
                operation = schema["paths"][path][method.lower()]
                operation["summary"] = OPERATION_SUMMARIES.get(route.name, operation["summary"])
                for parameter in operation.get("parameters", []):
                    parameter.setdefault("description", _parameter_description(path, parameter["name"], parameter["in"]))
                if permissions:
                    operation["security"] = [{"AccessKey": []}, {"SessionCookie": []}]
                    operation["responses"].setdefault("401", {"description": "Authentication failed"})
                    operation["responses"].setdefault("403", {"description": "The credential does not have the required permission"})
                    authentication = f"Required permission: `{'`, `'.join(permissions)}`."
                elif "public" in access:
                    operation["security"] = []
                    authentication = "Authentication: none."
                elif "browser" in access:
                    operation["security"] = [{"SessionCookie": []}]
                    operation["responses"].setdefault("401", {"description": "A valid browser session is required"})
                    operation["responses"].setdefault("403", {"description": "The request failed browser security checks"})
                    authentication = "Authentication: browser session."
                elif "principal" in access:
                    operation["security"] = [{"AccessKey": []}, {"SessionCookie": []}]
                    operation["responses"].setdefault("401", {"description": "Authentication failed"})
                    authentication = "Authentication: browser session or control-plane access key."
                elif "user" in access:
                    operation["security"] = [{"AccessKey": []}, {"SessionCookie": []}]
                    operation["responses"].setdefault("401", {"description": "An authenticated human account is required"})
                    authentication = "Authentication: human account using a browser session or control-plane access key."
                else:
                    continue
                operation["description"] = f"{operation['description']}\n\n{authentication}" if operation.get("description") else authentication
        return schema


def operation_id(route: APIRoute) -> str:
    return route.name
