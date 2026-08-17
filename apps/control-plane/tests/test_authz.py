from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient
from helpers import make_app, make_org, make_user, make_workspace, setup_control_plane
from test_api_hygiene import _api_routes

from contract import uuid7
from control_plane.authz import Permission


def _markers(route) -> list[str]:
    permissions = [
        str(permission)
        for dependency in route.dependant.dependencies
        if (permission := getattr(dependency.call, "required_permission", None)) is not None
    ]
    access = [access for dependency in route.dependant.dependencies if (access := getattr(dependency.call, "access", None)) is not None]
    return [*permissions, *access]


def test_every_route_declares_one_authorization_rule_and_every_permission_names_a_scope():
    problems = []
    for route in _api_routes(make_app()):
        for method in sorted(route.methods or ()):
            if len(_markers(route)) != 1:
                problems.append(f"{method} {route.path} carries {len(_markers(route))} authorization markers")
            permission_checks = [dependency.call for dependency in route.dependant.dependencies if hasattr(dependency.call, "required_permission")]
            if permission_checks and not all(getattr(check, "required_scope", "") for check in permission_checks):
                problems.append(f"{method} {route.path} has a permission without a tenant scope")
    assert problems == []


def test_routes_do_not_interpret_credential_or_standing_authority():
    route_dir = Path(__file__).parents[1] / "src" / "control_plane" / "routes"
    forbidden = (
        "principal_permissions",
        "permission_ceiling",
        ".boundary",
        "authority.org_id",
        "authority.workspace_id",
        "INSTANCE_ROLE_PERMISSIONS",
        "ORG_ROLE_PERMISSIONS",
        "WORKSPACE_ROLE_PERMISSIONS",
    )
    problems = [f"{path.name}: {term}" for path in route_dir.glob("*.py") for term in forbidden if term in path.read_text()]
    assert problems == []


def test_management_routes_name_their_scope_in_the_path():
    spec = make_app().openapi()
    paths = set(spec["paths"])
    assert "/api/v1/orgs/{org_id}/workspaces" in paths
    assert "/api/v1/orgs/{org_id}/users" in paths
    assert "/api/v1/orgs/{org_id}/provider-credentials" in paths
    assert "/api/v1/orgs/{org_id}/access-keys" in paths
    assert "/api/v1/orgs/{org_id}/workspaces/{workspace_ref}/access-keys" in paths
    assert "/api/v1/instance/access-keys" in paths
    assert not any(
        parameter.get("name") == "X-Org-Id"
        for item in spec["paths"].values()
        for operation in item.values()
        for parameter in operation.get("parameters", [])
    )


def test_access_markers_match_reality(tmp_path):
    cp = setup_control_plane(tmp_path)
    with TestClient(cp.app) as client:
        assert client.get("/api/v1/auth/me").status_code == 401
        assert client.post("/api/v1/auth/logout").status_code == 401
        assert client.post("/api/v1/auth/password", json={"current_password": "x", "new_password": "password123"}).status_code == 401


def test_permissions_docs_accept_any_authenticated_principal():
    spec = make_app().openapi()
    operation = spec["paths"]["/api/v1/auth/permissions"]["get"]
    assert operation["security"] == [{"AccessKey": []}, {"SessionCookie": []}]
    assert "human account" not in operation["description"]
    assert operation["summary"] == "Get Effective Permissions"
    assert spec["components"]["schemas"]["MyPermissionsOut"]["properties"]["permissions"]["description"]


def test_spec_advertises_the_enforced_permission():
    app = make_app()
    spec = app.openapi()
    problems = []
    for route in _api_routes(app):
        enforced = [
            str(permission)
            for dependency in route.dependant.dependencies
            if (permission := getattr(dependency.call, "required_permission", None)) is not None
        ]
        access = [access for dependency in route.dependant.dependencies if (access := getattr(dependency.call, "access", None)) is not None]
        for method in sorted(route.methods or ()):
            operation = spec["paths"]["/api/v1" + route.path][method.lower()]
            description = operation.get("description", "")
            if enforced and operation.get("security") != [{"AccessKey": []}, {"SessionCookie": []}]:
                problems.append(f"{method} {route.path} does not advertise bearer-or-cookie authentication")
            if enforced and f"Required permission: `{enforced[0]}`." not in description:
                problems.append(f"{method} {route.path} does not state its permission")
            if "public" in access and (operation.get("security") != [] or "Authentication: none." not in description):
                problems.append(f"{method} {route.path} does not advertise public access")
            if "browser" in access and operation.get("security") != [{"SessionCookie": []}]:
                problems.append(f"{method} {route.path} does not advertise browser-only access")
    assert problems == []


def test_openapi_is_written_for_external_consumers():
    spec = make_app().openapi()
    assert spec["info"].get("description")
    schemes = spec["components"]["securitySchemes"]
    assert set(schemes) == {"AccessKey", "SessionCookie"}
    assert all(scheme.get("description") for scheme in schemes.values())

    internal_terms = (
        "acting org",
        "acting user",
        "app.py",
        "composite foreign",
        "database refuses",
        "recordcreate",
        "route's tenant",
        "trapdoor",
    )
    problems = []
    descriptions = [spec["info"]["description"], *(tag.get("description", "") for tag in spec.get("tags", []))]
    descriptions.extend(schema.get("description", "") for schema in spec["components"]["schemas"].values())
    for path, item in spec["paths"].items():
        for method, operation in item.items():
            if method not in {"get", "post", "put", "patch", "delete"}:
                continue
            description = operation.get("description", "")
            if not description:
                problems.append(f"{method.upper()} {path} has no description")
            descriptions.append(description)
            problems.extend(
                f"{method.upper()} {path} does not describe {parameter['name']}"
                for parameter in operation.get("parameters", [])
                if not parameter.get("description")
            )
    public_text = "\n".join(descriptions).lower()
    problems.extend(f"OpenAPI exposes internal wording: {term}" for term in internal_terms if term in public_text)

    def schema_refs(value):
        if isinstance(value, dict):
            if ref := value.get("$ref"):
                yield ref.rsplit("/", 1)[-1]
            for nested in value.values():
                yield from schema_refs(nested)
        elif isinstance(value, list):
            for nested in value:
                yield from schema_refs(nested)

    request_schemas = {
        schema
        for item in spec["paths"].values()
        for method, operation in item.items()
        if method in {"get", "post", "put", "patch", "delete"}
        for schema in schema_refs(operation.get("requestBody", {}))
    }
    for schema_name in sorted(request_schemas):
        for field, field_schema in spec["components"]["schemas"][schema_name].get("properties", {}).items():
            if not field_schema.get("description"):
                problems.append(f"{schema_name}.{field} has no description")
    assert problems == []


def test_event_page_stays_flat_in_the_openapi_query_contract():
    operation = make_app().openapi()["paths"]["/api/v1/orgs/{org_id}/events"]["get"]
    query_parameters = {parameter["name"] for parameter in operation["parameters"] if parameter["in"] == "query"}
    assert query_parameters == {"before", "before_event_id", "after", "after_event_id", "limit"}


def test_permission_ceiling_restricts_actions_within_a_scope(tmp_path):
    cp = setup_control_plane(tmp_path)
    with TestClient(cp.app) as client:
        org_id = make_org(client, cp.headers())
        workspace_id = make_workspace(client, cp.headers(org_id))
        reader = cp.headers(org_id, permissions=[Permission.workspaces_read, Permission.inference_keys_read])
        assert client.get(f"/api/v1/orgs/{org_id}/workspaces", headers=reader).status_code == 200
        assert client.post(f"/api/v1/orgs/{org_id}/workspaces", json={"name": "blocked"}, headers=reader).status_code == 403
        assert client.get(f"/api/v1/orgs/{org_id}/workspaces/{workspace_id}/inference-keys", headers=reader).status_code == 200
        assert (
            client.post(f"/api/v1/orgs/{org_id}/workspaces/{workspace_id}/inference-keys", json={"label": "blocked"}, headers=reader).status_code
            == 403
        )


def test_org_scope_cannot_reach_instance_or_another_org(tmp_path):
    cp = setup_control_plane(tmp_path)
    with TestClient(cp.app) as client:
        root = cp.headers()
        first = make_org(client, root, "first")
        second = make_org(client, root, "second")
        key = cp.headers(first)
        assert client.get(f"/api/v1/orgs/{first}/workspaces", headers=key).status_code == 200
        assert client.get("/api/v1/users", headers=key).status_code == 403
        assert client.get(f"/api/v1/orgs/{first}", headers=key).status_code == 200
        assert client.get(f"/api/v1/orgs/{second}", headers=key).status_code == 403


def test_workspace_scope_cannot_reach_its_org_or_sibling(tmp_path):
    cp = setup_control_plane(tmp_path)
    with TestClient(cp.app) as client:
        org_id = make_org(client, cp.headers())
        org = cp.headers(org_id)
        first = make_workspace(client, org, "first")
        second = make_workspace(client, org, "second")
        key = cp.headers(org_id, workspace_id=first)
        assert client.get(f"/api/v1/orgs/{org_id}/workspaces/{first}", headers=key).status_code == 200
        assert client.get(f"/api/v1/orgs/{org_id}/workspaces/{second}", headers=key).status_code == 403
        assert client.get(f"/api/v1/orgs/{org_id}/workspaces", headers=key).status_code == 403


def test_workspace_usage_reader_sees_only_that_workspace(tmp_path):
    cp = setup_control_plane(tmp_path)
    with TestClient(cp.app) as client:
        root = cp.headers()
        org_id = make_org(client, root)
        org = cp.headers(org_id)
        first = make_workspace(client, org, "first")
        second = make_workspace(client, org, "second")
        viewer = make_user(tmp_path, "viewer@example.com")
        assert client.put(f"/api/v1/orgs/{org_id}/users/{viewer.id}", json={"role": "member"}, headers=org).status_code == 200
        assert client.put(f"/api/v1/orgs/{org_id}/workspaces/{first}/members/{viewer.id}", json={"role": "viewer"}, headers=org).status_code == 200
        minted = client.post(
            f"/api/v1/orgs/{org_id}/workspaces/{first}/access-keys",
            json={
                "label": "workspace-usage",
                "user_id": str(viewer.id),
                "permissions": [Permission.usage_read],
            },
            headers=root,
        ).json()["data"]
        events = [
            {
                "event_id": str(uuid7()),
                "request_id": str(uuid7()),
                "occurred_at": datetime.now(tz=UTC).isoformat(),
                "org_id": str(org_id),
                "workspace_id": str(workspace_id),
                "key_id": "key",
                "model_id": "model",
                "provider_id": "provider",
                "bundle_id": str(uuid4()),
                "input_tokens": 1,
                "output_tokens": 1,
                "cost_usd": 0,
                "latency_ms": 1,
                "status": "ok",
                "stream": False,
            }
            for workspace_id in (first, second)
        ]
        assert client.post("/api/v1/events", json=events, headers=root).status_code == 200

        key = {"authorization": f"Bearer {minted['token']}"}
        visible = client.get(f"/api/v1/orgs/{org_id}/workspaces/{first}/events", headers=key)
        assert visible.status_code == 200, visible.text
        assert {event["workspace_id"] for event in visible.json()["data"]} == {str(first)}
        assert client.get(f"/api/v1/orgs/{org_id}/workspaces/{second}/events", headers=key).status_code == 403
