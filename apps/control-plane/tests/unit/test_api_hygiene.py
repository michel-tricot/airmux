from __future__ import annotations

from typing import get_args, get_origin

from helpers import api_routes, make_app
from pydantic import BaseModel

from control_plane.deps import get_session
from control_plane.models.common.wire import Envelope


def _nested_models(tp: object, seen: set[type[BaseModel]] | None = None) -> set[type[BaseModel]]:
    """Every BaseModel reachable from a type annotation, through generics and model fields."""
    found = seen if seen is not None else set()
    if isinstance(tp, type) and issubclass(tp, BaseModel):
        if tp not in found:
            found.add(tp)
            for f in tp.model_fields.values():
                _nested_models(f.annotation, found)
    else:
        for arg in get_args(tp):
            _nested_models(arg, found)
    return found


def test_every_endpoint_declares_an_envelope():
    routes = api_routes(make_app())
    assert routes
    offenders = [
        f"{sorted(r.methods or ())} {r.path}"
        for r in routes
        if r.response_model is None or not (isinstance(r.response_model, type) and issubclass(r.response_model, Envelope))
    ]
    assert offenders == [], (
        f"Every endpoint responds {{'data': ...}}: annotate these with `-> Envelope[YourOut]` and return Envelope(data=...): {offenders}"
    )


def test_every_endpoint_is_tagged_for_docs():
    """ReDoc renders one sidebar section per tag: every operation carries a resource tag, every tag is declared with a description,
    and x-tagGroups covers every tag so none drop out of the grouped sidebar."""
    app = make_app()
    untagged = [f"{sorted(r.methods or ())} {r.path}" for r in api_routes(app) if not r.tags]
    assert untagged == [], f"Give these operations at least one resource tag: {untagged}"
    schema = app.openapi()
    used = {str(tag) for r in api_routes(app) for tag in r.tags}
    declared = {t["name"] for t in schema.get("tags", [])}
    grouped_tags = [tag for group in schema.get("x-tagGroups", []) for tag in group["tags"]]
    grouped = set(grouped_tags)
    assert used == declared, f"Declare every used tag in openapi_tags with a description: {used ^ declared}"
    assert used == grouped, f"List every tag in an x-tagGroups group or it disappears from the ReDoc sidebar: {used ^ grouped}"
    assert len(grouped_tags) == len(grouped), "Place each tag in exactly one ReDoc group"


def test_management_key_docs_distinguish_tenant_scopes():
    operations = {
        operation["operationId"]: operation["tags"]
        for methods in make_app().openapi()["paths"].values()
        for operation in methods.values()
        if "management_key" in operation["operationId"]
    }
    assert operations == {
        "list_instance_management_keys": ["Instance Management Keys"],
        "create_instance_management_key": ["Instance Management Keys"],
        "list_org_management_keys": ["Organization Management Keys"],
        "create_org_management_key": ["Organization Management Keys"],
        "list_workspace_management_keys": ["Workspace Management Keys"],
        "create_workspace_management_key": ["Workspace Management Keys"],
        "revoke_management_key": ["Instance Management Keys", "Organization Management Keys", "Workspace Management Keys"],
        "update_management_key_permissions": ["Instance Management Keys", "Organization Management Keys", "Workspace Management Keys"],
    }


def test_documentation_groups_follow_authority_scopes():
    app = make_app()
    groups = {tag: group["name"] for group in app.openapi()["x-tagGroups"] for tag in group["tags"]}
    expected_by_scope = {
        "instance_scope": {"Instance"},
        "org_scope": {"Organization"},
        "workspace_scope": {"Workspace"},
        "bundle_scope": {"Data Plane API"},
    }
    expected_by_operation = {
        "revoke_management_key": {"Instance", "Organization", "Workspace"},
        "get_provider_credential": {"Organization", "Workspace"},
        "update_provider_credential": {"Organization", "Workspace"},
        "rotate_provider_credential": {"Organization", "Workspace"},
        "delete_provider_credential": {"Organization", "Workspace"},
        "ingest_events": {"Data Plane API"},
        "heartbeat": {"Data Plane API"},
    }
    offenders = sorted(
        f"{route.name}: expected {sorted(expected)}, documented under {sorted(actual)}"
        for route in api_routes(app)
        for dependency in route.dependant.dependencies
        if (scope := getattr(dependency.call, "required_scope", None)) is not None
        if (expected := expected_by_operation.get(route.name, expected_by_scope.get(scope))) is not None
        if (actual := {groups[tag] for tag in route.tags}) != expected
    )
    assert offenders == []


def test_permission_requirements_are_machine_readable():
    app = make_app()
    schema = app.openapi()
    operations = {operation["operationId"]: operation for methods in schema["paths"].values() for operation in methods.values()}
    expected = {
        route.name: [
            {
                "scope": dependency.call.required_scope,
                "anyOf": [permission.value for permission in rule],
            }
            for dependency in route.dependant.dependencies
            if hasattr(dependency.call, "required_permissions")
            for rule in dependency.call.required_permission_rules
        ]
        for route in api_routes(app)
    }
    assert {name: operation.get("x-airllm-authority", []) for name, operation in operations.items()} == expected


def test_membership_and_workspace_docs_are_resource_specific():
    operations = {operation["operationId"]: operation["tags"] for methods in make_app().openapi()["paths"].values() for operation in methods.values()}
    assert {operation: operations[operation] for operation in ("list_org_users", "add_org_user", "remove_org_user")} == {
        "list_org_users": ["Organization Members"],
        "add_org_user": ["Organization Members"],
        "remove_org_user": ["Organization Members"],
    }
    assert {operation: operations[operation] for operation in ("create_org_service_account", "delete_org_service_account")} == {
        "create_org_service_account": ["Organization Service Accounts"],
        "delete_org_service_account": ["Organization Service Accounts"],
    }
    assert {operation: operations[operation] for operation in ("create_workspace", "list_workspaces")} == {
        "create_workspace": ["Organization Workspaces"],
        "list_workspaces": ["Organization Workspaces"],
    }
    assert {operation: operations[operation] for operation in ("get_workspace", "update_workspace", "delete_workspace")} == {
        "get_workspace": ["Workspace Settings"],
        "update_workspace": ["Workspace Settings"],
        "delete_workspace": ["Workspace Settings"],
    }
    assert {operation: operations[operation] for operation in ("list_members", "list_member_candidates", "add_member", "remove_member")} == {
        "list_members": ["Workspace Members"],
        "list_member_candidates": ["Workspace Members"],
        "add_member": ["Workspace Members"],
        "remove_member": ["Workspace Members"],
    }


def test_operation_ids_are_the_handler_names():
    """Generated clients name every method after operationId, so the ids are the handler names: FastAPI's default bakes the path
    and the verb into each one and turns useListOrgs into useListOrgsV1OrgsGet."""
    app = make_app()
    operation_ids = [op["operationId"] for operations in app.openapi()["paths"].values() for op in operations.values()]
    assert sorted(operation_ids) == sorted(r.name for r in api_routes(app))
    duplicates = sorted({name for name in operation_ids if operation_ids.count(name) > 1})
    assert duplicates == [], f"Two handlers share a name, so one client method overwrites the other: {duplicates}"


def test_no_table_model_crosses_the_wire():
    """Rows never serialize directly: every response payload goes through an Out model, so api_hidden fields cannot leak."""
    offenders = sorted(
        f"{model.__name__} via {route.path}"
        for route in api_routes(make_app())
        for model in _nested_models(route.response_model)
        if hasattr(model, "__table__")
    )
    assert offenders == [], (
        f"Table rows must not serialize directly, or api_hidden fields leak. Serve a RecordOut[Table] subclass "
        f"(XOut.model_validate(row)): {offenders}"
    )


def test_no_table_model_is_accepted_as_input():
    """Callers never post a table shape: a table model as a body would accept hidden and server-owned columns."""
    offenders = sorted(
        f"{model.__name__} via {sorted(route.methods or ())} {route.path}"
        for route in api_routes(make_app())
        for field in route.dependant.body_params
        for model in _nested_models(field.field_info.annotation)
        if hasattr(model, "__table__")
    )
    assert offenders == [], f"Accept a RecordCreate[Table] or RecordUpdate[Table] subclass instead: {offenders}"


def test_every_body_model_rejects_unknown_fields():
    offenders = sorted(
        f"{model.__name__} via {sorted(route.methods or ())} {route.path}"
        for route in api_routes(make_app())
        for field in route.dependant.body_params
        for model in _nested_models(field.field_info.annotation)
        if model.model_config.get("extra") != "forbid"
    )
    assert offenders == [], f"Request bodies must fail on misspelled or obsolete fields: {offenders}"


def test_payloads_are_named_models():
    """Anonymous dict payloads document nothing in OpenAPI; every envelope carries a named model."""
    offenders = []
    for route in api_routes(make_app()):
        assert route.response_model is not None
        data = route.response_model.model_fields["data"].annotation
        inner = get_args(data)[0] if get_origin(data) is list else data
        if not (isinstance(inner, type) and issubclass(inner, BaseModel)):
            offenders.append(f"{sorted(route.methods or ())} {route.path} -> {data}")
    assert offenders == [], (
        f"Replace anonymous payloads with a named model colocated with its resource (an action Out if no table backs it): {offenders}"
    )


def test_response_schemas_are_pure_envelopes():
    spec = make_app().openapi()
    offenders = []
    for path, ops in spec["paths"].items():
        for method, op in ops.items():
            schema = op["responses"]["200"]["content"]["application/json"]["schema"]
            if "$ref" in schema:
                schema = spec["components"]["schemas"][schema["$ref"].rsplit("/", 1)[1]]
            if set(schema.get("properties", {})) != {"data"}:
                offenders.append(f"{method.upper()} {path}")
    assert offenders == []


def test_request_transactions_are_shared_without_polluting_route_signatures():
    app = make_app()
    v1 = [
        router
        for route in app.routes
        if (router := getattr(route, "original_router", None)) is not None and getattr(router, "prefix", None) == "/api/v1"
    ]
    assert len(v1) == 1
    assert any(dependency.dependency is get_session and dependency.scope == "function" for dependency in v1[0].dependencies)
    routes = api_routes(app)
    raw_sql = {"/events", "/heartbeat"}
    polluted = [
        route.path
        for route in routes
        if route.path not in raw_sql and any(parameter.name == "_session" for parameter in route.dependant.dependencies)
    ]
    assert polluted == []
