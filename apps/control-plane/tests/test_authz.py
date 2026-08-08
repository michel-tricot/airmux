from __future__ import annotations

from fastapi.testclient import TestClient
from helpers import make_app, make_org, setup_control_plane
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
    account routes authenticated as a user with no org or scope semantics. Instance routes
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
        f"dependencies=[public()], or dependencies=[user_scoped()] to the route decorator: {problems}"
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
            advertised = [scope for entry in operation.get("security", []) for scope in entry.get("HTTPBearer", [])]
            description = operation.get("description", "")
            if advertised != enforced:
                problems.append(f"{method} /v1{route.path} enforces {enforced} but advertises {advertised}")
            if enforced and f"`{enforced[0]}`" not in description:
                problems.append(f"{method} /v1{route.path} description does not state the required scope")
            if "public" in access and (operation.get("security") != [] or "No authentication required." not in description):
                problems.append(f"{method} /v1{route.path} is public() but the spec does not say so")
            if "user" in access and "Requires an authenticated user" not in description:
                problems.append(f"{method} /v1{route.path} is user_scoped() but the spec does not say so")
    assert problems == [], f"The spec must advertise exactly what the markers enforce; fix the openapi() derivation, not the spec: {problems}"


def test_spec_stamping_is_idempotent_across_requests():
    """FastAPI caches the generated schema and returns the same dict on every call; the scope
    stamping must not compound on it, or each page refresh grows every description by one line."""
    app = make_app()
    first = app.openapi()["paths"]["/v1/org/keys"]["post"].get("description")
    second = app.openapi()["paths"]["/v1/org/keys"]["post"].get("description")
    assert first == second
    assert first is not None
    assert first.count("Requires the") == 1


def _claims(scopes) -> ManagementClaims:
    return ManagementClaims(token_id=uuid7(), org_id=uuid7(), user_id=uuid7(), scopes=frozenset(scopes))


def test_allowed_is_a_pure_scope_membership_check():
    assert allowed(_claims(ALL_SCOPES), Scope.keys_write)
    assert allowed(_claims({"keys:read"}), Scope.keys_read)
    assert not allowed(_claims({"keys:read"}), Scope.keys_write)
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
        reader = cp.headers(org_id=o1, scopes=["keys:read"])
        assert client.get("/v1/org/keys", headers=reader).status_code == 200
        assert client.post("/v1/org/keys", headers=reader).status_code == 403
        assert client.post("/v1/org/bundles/compile", headers=reader).status_code == 403
        assert client.get("/v1/org/events", headers=reader).status_code == 403


def test_unscoped_token_keeps_full_authority(tmp_path):
    cp = setup_control_plane(tmp_path)
    with TestClient(cp.app) as client:
        o1 = _seed_org(client, cp.headers())
        org = cp.headers(org_id=o1)
        assert client.post("/v1/org/keys", json={"label": "k"}, headers=org).status_code == 200
        assert client.get("/v1/org/keys", headers=org).status_code == 200


def test_sync_scope_covers_the_data_plane_surface_and_nothing_else(tmp_path):
    cp = setup_control_plane(tmp_path)
    with TestClient(cp.app) as client:
        o1 = _seed_org(client, cp.headers())
        assert client.post("/v1/org/bundles/compile", headers=cp.headers(org_id=o1)).status_code == 200
        sync = cp.headers(org_id=o1, scopes=["sync"])
        assert client.get("/v1/bundle/latest", headers=sync).status_code == 200
        assert client.post("/v1/events", json=[], headers=sync).status_code == 200
        assert client.get("/v1/org/keys", headers=sync).status_code == 403
        assert client.get("/v1/taxonomy", headers=sync).status_code == 403


def test_mint_accepts_scopes_and_rejects_unknown_ones(tmp_path):
    cp = setup_control_plane(tmp_path)
    with TestClient(cp.app) as client:
        root = cp.headers()
        o1 = _seed_org(client, root)
        user = client.post("/v1/users", json={"email": "dev@example.com"}, headers=root).json()["data"]
        assert client.put(f"/v1/users/{user['id']}/orgs/{o1}", headers=root).status_code == 200
        bad = client.post(f"/v1/users/{user['id']}/tokens", json={"org_id": str(o1), "scopes": ["nope"], "label": "t"}, headers=root)
        assert bad.status_code == 422
        minted = client.post(f"/v1/users/{user['id']}/tokens", json={"org_id": str(o1), "scopes": ["keys:read"], "label": "t"}, headers=root)
        assert minted.status_code == 200
        assert minted.json()["data"]["scopes"] == ["keys:read"]
        rows = client.get("/v1/instance/tokens", params={"org_id": str(o1)}, headers=root).json()["data"]
        assert {r["id"]: r["scopes"] for r in rows}[minted.json()["data"]["id"]] == ["keys:read"]


def test_restricted_instance_credential(tmp_path):
    cp = setup_control_plane(tmp_path)
    with TestClient(cp.app) as client:
        auditor = cp.headers(scopes=["users:read", "tokens:read"])
        assert client.get("/v1/users", headers=auditor).status_code == 200
        assert client.get("/v1/instance/tokens", headers=auditor).status_code == 200
        assert client.get("/v1/orgs", headers=auditor).status_code == 403
        assert client.post("/v1/users", json={"email": "x@example.com"}, headers=auditor).status_code == 403
        assert client.post("/v1/taxonomy/providers", json={}, headers=auditor).status_code == 403
        provisioner = cp.headers(scopes=["orgs:write", "users:write"])
        assert client.post("/v1/orgs", json={"name": "o2"}, headers=provisioner).status_code == 200
        assert client.get("/v1/orgs", headers=provisioner).status_code == 403
