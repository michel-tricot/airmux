from __future__ import annotations

from datetime import UTC, datetime
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


def test_every_route_declares_one_authorization_rule_and_every_permission_names_a_target():
    problems = []
    for route in _api_routes(make_app()):
        for method in sorted(route.methods or ()):
            if len(_markers(route)) != 1:
                problems.append(f"{method} {route.path} carries {len(_markers(route))} authorization markers")
            permission_checks = [dependency.call for dependency in route.dependant.dependencies if hasattr(dependency.call, "required_permission")]
            if permission_checks and not all(getattr(check, "required_target", "") for check in permission_checks):
                problems.append(f"{method} {route.path} has a permission without a tenant target")
    assert problems == []


def test_access_markers_match_reality(tmp_path):
    cp = setup_control_plane(tmp_path)
    with TestClient(cp.app) as client:
        assert client.get("/v1/auth/me").status_code == 401
        assert client.post("/v1/auth/logout").status_code == 401
        assert client.post("/v1/auth/password", json={"current_password": "x", "new_password": "password123"}).status_code == 401


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
            operation = spec["paths"]["/v1" + route.path][method.lower()]
            description = operation.get("description", "")
            if enforced and operation.get("security") != [{"HTTPBearer": []}, {"SessionCookie": []}]:
                problems.append(f"{method} {route.path} does not advertise bearer-or-cookie authentication")
            if enforced and f"`{enforced[0]}`" not in description:
                problems.append(f"{method} {route.path} does not state its permission")
            if "public" in access and (operation.get("security") != [] or "No authentication required." not in description):
                problems.append(f"{method} {route.path} does not advertise public access")
            if "browser" in access and operation.get("security") != [{"SessionCookie": []}]:
                problems.append(f"{method} {route.path} does not advertise browser-only access")
    assert problems == []


def test_event_page_stays_flat_in_the_openapi_query_contract():
    operation = make_app().openapi()["paths"]["/v1/org/events"]["get"]
    query_parameters = {parameter["name"] for parameter in operation["parameters"] if parameter["in"] == "query"}
    assert query_parameters == {"before", "before_event_id", "after", "after_event_id", "limit", "workspace_id"}


def test_permission_ceiling_restricts_actions_within_a_boundary(tmp_path):
    cp = setup_control_plane(tmp_path)
    with TestClient(cp.app) as client:
        org_id = make_org(client, cp.headers())
        workspace_id = make_workspace(client, cp.headers(org_id))
        reader = cp.headers(org_id, permissions=[Permission.workspaces_read, Permission.inference_keys_read])
        assert client.get("/v1/org/workspaces", headers=reader).status_code == 200
        assert client.post("/v1/org/workspaces", json={"name": "blocked"}, headers=reader).status_code == 403
        assert client.get(f"/v1/org/workspaces/{workspace_id}/inference-keys", headers=reader).status_code == 200
        assert client.post(f"/v1/org/workspaces/{workspace_id}/inference-keys", json={"label": "blocked"}, headers=reader).status_code == 403


def test_org_boundary_cannot_reach_instance_or_another_org(tmp_path):
    cp = setup_control_plane(tmp_path)
    with TestClient(cp.app) as client:
        root = cp.headers()
        first = make_org(client, root, "first")
        second = make_org(client, root, "second")
        key = cp.headers(first)
        assert client.get("/v1/org/workspaces", headers=key).status_code == 200
        assert client.get("/v1/users", headers=key).status_code == 403
        assert client.get(f"/v1/orgs/{first}", headers=key).status_code == 200
        assert client.get(f"/v1/orgs/{second}", headers=key).status_code == 403


def test_workspace_boundary_cannot_reach_its_org_or_sibling(tmp_path):
    cp = setup_control_plane(tmp_path)
    with TestClient(cp.app) as client:
        org_id = make_org(client, cp.headers())
        org = cp.headers(org_id)
        first = make_workspace(client, org, "first")
        second = make_workspace(client, org, "second")
        key = cp.headers(org_id, workspace_id=first)
        assert client.get(f"/v1/org/workspaces/{first}", headers=key).status_code == 200
        assert client.get(f"/v1/org/workspaces/{second}", headers=key).status_code == 403
        assert client.get("/v1/org/workspaces", headers=key).status_code == 403


def test_workspace_usage_reader_sees_only_that_workspace(tmp_path):
    cp = setup_control_plane(tmp_path)
    with TestClient(cp.app) as client:
        root = cp.headers()
        org_id = make_org(client, root)
        org = cp.headers(org_id)
        first = make_workspace(client, org, "first")
        second = make_workspace(client, org, "second")
        viewer = make_user(tmp_path, "viewer@example.com")
        assert client.put(f"/v1/org/users/{viewer.id}", json={"role": "member"}, headers=org).status_code == 200
        assert client.put(f"/v1/org/workspaces/{first}/members/{viewer.id}", json={"role": "viewer"}, headers=org).status_code == 200
        minted = client.post(
            "/v1/access-keys",
            json={
                "label": "workspace-usage",
                "user_id": str(viewer.id),
                "org_id": str(org_id),
                "workspace_id": str(first),
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
        assert client.post("/v1/events", json=events, headers=root).status_code == 200

        key = {"authorization": f"Bearer {minted['token']}"}
        visible = client.get("/v1/org/events", headers=key)
        assert visible.status_code == 200, visible.text
        assert {event["workspace_id"] for event in visible.json()["data"]} == {str(first)}
        assert client.get("/v1/org/events", params={"workspace_id": str(second)}, headers=key).status_code == 403
