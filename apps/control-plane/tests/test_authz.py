from __future__ import annotations

from fastapi.testclient import TestClient
from helpers import make_app, make_org, make_user, make_workspace, setup_control_plane
from test_api_hygiene import _api_routes

from contract import uuid7
from control_plane.authz import ALL_SCOPES, Scope, allowed
from control_plane.keys import ManagementClaims


def _markers(route) -> list[str]:
    scopes = [str(scope) for dep in route.dependant.dependencies if (scope := getattr(dep.call, "required_scope", None)) is not None]
    access = [access for dep in route.dependant.dependencies if (access := getattr(dep.call, "access", None)) is not None]
    return [*scopes, *access]


def test_every_route_declares_its_authorization():
    """Every endpoint carries exactly one authorization marker on its decorator: require(Scope...)
    for scoped access, public() for deliberately unauthenticated routes, user_scoped() for
    account routes authenticated as a user with no org or scope semantics. browser_scoped()
    marks cookie-only account routes. Instance routes
    additionally gate on instance_scope, which is the row-scope axis, not a marker."""
    app = make_app()
    problems = [
        f"{method} {route.path} carries {len(_markers(route))} markers"
        for route in _api_routes(app)
        for method in sorted(route.methods or ())
        if len(_markers(route)) != 1
    ]
    assert problems == [], (
        f"Every route declares its authorization exactly once: add dependencies=[require(Scope...)], "
        f"dependencies=[public()], dependencies=[user_scoped()], or dependencies=[browser_scoped()] to the route decorator: {problems}"
    )


def test_access_markers_match_reality(tmp_path):
    """public() routes answer without credentials; user_scoped() routes 401 without them.
    Catches a route whose marker drifts from what its handler enforces."""
    cp = setup_control_plane(tmp_path)
    with TestClient(cp.app) as client:
        assert client.get("/v1/auth/me").status_code == 401
        assert client.post("/v1/auth/logout").status_code == 401
        assert client.post("/v1/auth/password", json={"current_password": "x", "new_password": "password123"}).status_code == 401


def test_spec_advertises_the_enforced_scope():
    """Every operation's security array and description are derived from the route's marker by
    ControlPlaneApp.openapi(): scoped routes advertise exactly the enforced scope, public routes
    advertise an empty security array, user-scoped routes state their access in the description."""
    app = make_app()
    spec = app.openapi()
    problems = []
    for route in _api_routes(app):
        enforced = [str(s) for dep in route.dependant.dependencies if (s := getattr(dep.call, "required_scope", None)) is not None]
        access = [a for dep in route.dependant.dependencies if (a := getattr(dep.call, "access", None)) is not None]
        for method in sorted(route.methods or ()):
            operation = spec["paths"]["/v1" + route.path][method.lower()]
            description = operation.get("description", "")
            if enforced and operation.get("security") != [{"HTTPBearer": []}, {"SessionCookie": []}]:
                problems.append(f"{method} {route.path} does not advertise bearer-or-cookie authentication")
            if enforced and f"`{enforced[0]}`" not in description:
                problems.append(f"{method} {route.path} description does not state the required scope")
            if "public" in access and (operation.get("security") != [] or "No authentication required." not in description):
                problems.append(f"{method} {route.path} is public() but the spec does not say so")
            if "user" in access and (
                operation.get("security") != [{"HTTPBearer": []}, {"SessionCookie": []}] or "Requires an authenticated user" not in description
            ):
                problems.append(f"{method} {route.path} is user_scoped() but the spec does not say so")
            if "browser" in access and (operation.get("security") != [{"SessionCookie": []}] or "Requires a browser session" not in description):
                problems.append(f"{method} {route.path} is browser_scoped() but the spec does not say so")
    assert problems == [], f"The spec must advertise exactly what the markers enforce; fix the openapi() derivation, not the spec: {problems}"


def test_spec_stamping_is_idempotent_across_requests():
    """FastAPI caches the generated schema and returns the same dict on every call; the scope
    stamping must not compound on it, or each page refresh grows every description by one line."""
    app = make_app()
    first = app.openapi()["paths"]["/v1/org/workspaces"]["post"].get("description")
    second = app.openapi()["paths"]["/v1/org/workspaces"]["post"].get("description")
    assert first == second
    assert first is not None
    assert first.count("Requires the") == 1


def test_spec_describes_cookie_and_bearer_authentication_truthfully():
    spec = make_app().openapi()
    schemes = spec["components"]["securitySchemes"]
    assert schemes["SessionCookie"] == {"type": "apiKey", "in": "cookie", "name": "airllm_session"}
    assert spec["paths"]["/v1/auth/login"]["post"]["security"] == []
    assert spec["paths"]["/v1/auth/me"]["get"]["security"] == [{"HTTPBearer": []}, {"SessionCookie": []}]
    assert spec["paths"]["/v1/auth/cli/request"]["get"]["security"] == [{"SessionCookie": []}]
    assert spec["paths"]["/v1/org/workspaces"]["get"]["security"] == [{"HTTPBearer": []}, {"SessionCookie": []}]

    internal = {"airllm_session", "X-Requested-With", "Sec-Fetch-Site"}
    parameters = {
        parameter["name"]
        for operations in spec["paths"].values()
        for operation in operations.values()
        for parameter in operation.get("parameters", [])
    }
    assert parameters.isdisjoint(internal)


def _claims(scopes) -> ManagementClaims:
    return ManagementClaims(token_id=uuid7(), org_id=uuid7(), user_id=uuid7(), scopes=frozenset(scopes))


def test_allowed_is_a_pure_scope_membership_check():
    assert allowed(_claims(ALL_SCOPES), Scope.inference_keys_write)
    assert allowed(_claims({"inference-keys:read"}), Scope.inference_keys_read)
    assert not allowed(_claims({"inference-keys:read"}), Scope.inference_keys_write)
    assert not allowed(_claims(()), Scope.sync)


def test_claims_default_to_no_authority():
    """A construction site that forgets scopes fails closed; full authority is always an explicit ALL_SCOPES grant."""
    claims = ManagementClaims(token_id=uuid7(), org_id=None, user_id=uuid7())
    assert claims.scopes == frozenset()
    assert all(not allowed(claims, scope) for scope in Scope)


def _seed_org(client, root):
    return make_org(client, root, "o1")


def test_scoped_token_restricts_verbs_within_the_org(tmp_path):
    cp = setup_control_plane(tmp_path)
    with TestClient(cp.app) as client:
        o1 = _seed_org(client, cp.headers())
        ws = make_workspace(client, cp.headers(org_id=o1))
        reader = cp.headers(org_id=o1, scopes=["workspaces:read", "inference-keys:read"])
        assert client.get("/v1/org/workspaces", headers=reader).status_code == 200
        assert client.post("/v1/org/workspaces", headers=reader).status_code == 403
        assert client.get(f"/v1/org/workspaces/{ws}/inference-keys", headers=reader).status_code == 200
        assert client.post(f"/v1/org/workspaces/{ws}/inference-keys", headers=reader).status_code == 403
        assert client.post("/v1/org/bundles/compile", headers=reader).status_code == 403
        assert client.get("/v1/org/events", headers=reader).status_code == 403


def test_unscoped_token_keeps_full_authority(tmp_path):
    cp = setup_control_plane(tmp_path)
    with TestClient(cp.app) as client:
        o1 = _seed_org(client, cp.headers())
        org = cp.headers(org_id=o1)
        ws = make_workspace(client, org)
        assert client.post(f"/v1/org/workspaces/{ws}/inference-keys", json={"label": "k"}, headers=org).status_code == 200
        assert client.get(f"/v1/org/workspaces/{ws}/inference-keys", headers=org).status_code == 200


def test_the_org_lifecycle_verbs_are_three_separate_scopes(tmp_path):
    """orgs:create founds an org, orgs:write governs one that exists, orgs:delete destroys it with
    everything inside. A credential trusted to rename the orgs it was given is not thereby trusted
    to provision new ones, and neither one may call delete_with_contents."""
    cp = setup_control_plane(tmp_path)
    with TestClient(cp.app) as client:
        existing = _seed_org(client, cp.headers())
        curator = cp.headers(scopes=["orgs:write"])
        assert client.post("/v1/orgs", json={"name": "o-curator"}, headers=curator).status_code == 403
        assert client.patch(f"/v1/orgs/{existing}", json={"name": "renamed"}, headers=curator).status_code == 200
        assert client.delete(f"/v1/orgs/{existing}", headers=curator).status_code == 403
        provisioner = cp.headers(scopes=["orgs:create"])
        founded = client.post("/v1/orgs", json={"name": "o-provisioner"}, headers=provisioner)
        assert founded.status_code == 200
        assert client.patch(f"/v1/orgs/{existing}", json={"name": "nope"}, headers=provisioner).status_code == 403
        assert client.delete(f"/v1/orgs/{existing}", headers=provisioner).status_code == 403
        remover = cp.headers(scopes=["orgs:delete"])
        assert client.post("/v1/orgs", json={"name": "o-remover"}, headers=remover).status_code == 403
        assert client.patch(f"/v1/orgs/{existing}", json={"name": "nope"}, headers=remover).status_code == 403
        assert client.delete(f"/v1/orgs/{founded.json()['data']['id']}", headers=remover).status_code == 200


def test_the_workspace_lifecycle_verbs_are_three_separate_scopes(tmp_path):
    cp = setup_control_plane(tmp_path)
    with TestClient(cp.app) as client:
        o1 = _seed_org(client, cp.headers())
        ws = make_workspace(client, cp.headers(org_id=o1))
        curator = cp.headers(org_id=o1, scopes=["workspaces:write"])
        assert client.post("/v1/org/workspaces", json={"name": "ws-curator"}, headers=curator).status_code == 403
        assert client.patch(f"/v1/org/workspaces/{ws}", json={"name": "renamed"}, headers=curator).status_code == 200
        assert client.delete(f"/v1/org/workspaces/{ws}", headers=curator).status_code == 403
        provisioner = cp.headers(org_id=o1, scopes=["workspaces:create"])
        founded = client.post("/v1/org/workspaces", json={"name": "ws-provisioner"}, headers=provisioner)
        assert founded.status_code == 200
        assert client.patch(f"/v1/org/workspaces/{ws}", json={"name": "nope"}, headers=provisioner).status_code == 403
        assert client.delete(f"/v1/org/workspaces/{ws}", headers=provisioner).status_code == 403
        remover = cp.headers(org_id=o1, scopes=["workspaces:delete"])
        assert client.post("/v1/org/workspaces", json={"name": "ws-remover"}, headers=remover).status_code == 403
        assert client.delete(f"/v1/org/workspaces/{founded.json()['data']['id']}", headers=remover).status_code == 200


def test_sync_scope_covers_the_data_plane_surface_and_nothing_else(tmp_path):
    cp = setup_control_plane(tmp_path)
    with TestClient(cp.app) as client:
        o1 = _seed_org(client, cp.headers())
        assert client.post("/v1/org/bundles/compile", headers=cp.headers(org_id=o1)).status_code == 200
        sync = cp.headers(org_id=o1, scopes=["sync"])
        assert client.get("/v1/bundle/latest", headers=sync).status_code == 200
        assert client.post("/v1/events", json=[], headers=sync).status_code == 200
        assert client.get("/v1/org/workspaces", headers=sync).status_code == 403
        assert client.get("/v1/taxonomy", headers=sync).status_code == 403


def test_mint_accepts_scopes_and_rejects_unknown_ones(tmp_path):
    cp = setup_control_plane(tmp_path)
    with TestClient(cp.app) as client:
        root = cp.headers()
        o1 = _seed_org(client, root)
        user = make_user(tmp_path, "dev@example.com")
        assert client.put(f"/v1/org/users/{user.id}", headers=cp.headers(o1)).status_code == 200
        bad = client.post("/v1/org/management-keys", json={"user_id": str(user.id), "scopes": ["nope"], "label": "t"}, headers=cp.headers(org_id=o1))
        assert bad.status_code == 422
        minted = client.post(
            "/v1/org/management-keys", json={"user_id": str(user.id), "scopes": ["inference-keys:read"], "label": "t"}, headers=cp.headers(org_id=o1)
        )
        assert minted.status_code == 200
        assert minted.json()["data"]["scopes"] == ["inference-keys:read"]
        rows = client.get("/v1/instance/management-keys", params={"org_id": str(o1)}, headers=root).json()["data"]
        assert {r["id"]: r["scopes"] for r in rows}[minted.json()["data"]["id"]] == ["inference-keys:read"]


def test_restricted_instance_credential(tmp_path):
    cp = setup_control_plane(tmp_path)
    with TestClient(cp.app) as client:
        auditor = cp.headers(scopes=["users:read", "management-keys:read"])
        assert client.get("/v1/users", headers=auditor).status_code == 200
        assert client.get("/v1/instance/management-keys", headers=auditor).status_code == 200
        assert client.get("/v1/orgs", headers=auditor).status_code == 403
        assert client.post("/v1/service-accounts", json={"name": "x"}, headers=auditor).status_code == 403
        assert client.post("/v1/taxonomy/providers", json={}, headers=auditor).status_code == 403
        provisioner = cp.headers(scopes=["orgs:create", "users:write"])
        assert client.post("/v1/orgs", json={"name": "o2"}, headers=provisioner).status_code == 200
        assert client.get("/v1/orgs", headers=provisioner).status_code == 403
