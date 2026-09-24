from __future__ import annotations

from helpers import api_routes, make_app


def _markers(route) -> list[str]:
    permission_rules = [
        tuple(str(permission) for permission in permissions)
        for dependency in route.dependant.dependencies
        if (permissions := getattr(dependency.call, "required_permissions", None)) is not None
    ]
    access = [access for dependency in route.dependant.dependencies if (access := getattr(dependency.call, "access", None)) is not None]
    return [*(", ".join(rule) for rule in permission_rules), *access]


def test_every_route_declares_one_authorization_rule_and_every_permission_names_a_scope():
    problems = []
    for route in api_routes(make_app()):
        for method in sorted(route.methods or ()):
            if len(_markers(route)) != 1:
                problems.append(f"{method} {route.path} carries {len(_markers(route))} authorization markers")
            permission_checks = [dependency.call for dependency in route.dependant.dependencies if hasattr(dependency.call, "required_permissions")]
            if permission_checks and not all(getattr(check, "required_scope", "") for check in permission_checks):
                problems.append(f"{method} {route.path} has a permission without a tenant scope")
    assert problems == []


def test_management_routes_name_their_scope_in_the_path():
    spec = make_app().openapi()
    paths = set(spec["paths"])
    assert "/api/v1/organizations/{org_id}/workspaces" in paths
    assert "/api/v1/organizations/{org_id}/users" in paths
    assert "/api/v1/organizations/{org_id}/provider-credentials" in paths
    assert "/api/v1/organizations/{org_id}/management-keys" in paths
    assert "/api/v1/organizations/{org_id}/workspaces/{workspace_ref}/management-keys" in paths
    assert "/api/v1/instance/management-keys" in paths
    assert not any(
        parameter.get("name") == "X-Org-Id"
        for item in spec["paths"].values()
        for operation in item.values()
        for parameter in operation.get("parameters", [])
    )


def test_permissions_docs_accept_any_authenticated_principal():
    spec = make_app().openapi()
    operation = spec["paths"]["/api/v1/auth/permissions"]["get"]
    assert operation["security"] == [{"ManagementKey": []}, {"SessionCookie": []}]
    assert "human account" not in operation["description"]
    assert operation["summary"] == "Get Effective Permissions"
    assert spec["components"]["schemas"]["MyPermissionsOut"]["properties"]["permissions"]["description"]


def test_spec_advertises_the_enforced_permission():
    app = make_app()
    spec = app.openapi()
    problems = []
    for route in api_routes(app):
        enforced = [
            tuple(str(permission) for permission in rule)
            for dependency in route.dependant.dependencies
            if getattr(dependency.call, "required_permissions", None) is not None
            for rule in dependency.call.required_permission_rules
        ]
        access = [access for dependency in route.dependant.dependencies if (access := getattr(dependency.call, "access", None)) is not None]
        for method in sorted(route.methods or ()):
            operation = spec["paths"]["/api/v1" + route.path][method.lower()]
            description = operation.get("description", "")
            if enforced and operation.get("security") != [{"ManagementKey": []}, {"SessionCookie": []}]:
                problems.append(f"{method} {route.path} does not advertise bearer-or-cookie authentication")
            permissions = [permission for rule in enforced for permission in rule]
            documented = (
                f"Required permission: one of `{'`, `'.join(permissions)}`."
                if len(enforced) == 1 and len(enforced[0]) > 1
                else f"Required permissions: {' and '.join(f'`{permission}`' for permission in permissions)}."
                if len(enforced) > 1
                else f"Required permission: `{permissions[0]}`."
                if permissions
                else ""
            )
            if enforced and documented not in description:
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
    assert set(schemes) == {"ManagementKey", "SessionCookie"}
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


def test_event_page_uses_the_shared_query_contract():
    operation = make_app().openapi()["paths"]["/api/v1/organizations/{org_id}/events"]["get"]
    query_parameters = {parameter["name"] for parameter in operation["parameters"] if parameter["in"] == "query"}
    assert query_parameters == {"cursor", "limit"}
