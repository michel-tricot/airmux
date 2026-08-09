from __future__ import annotations

from typing import get_args, get_origin

from helpers import make_app
from pydantic import BaseModel

from control_plane.app import _api_routes as _walk_routes
from control_plane.models.common.wire import Envelope


def _api_routes(app):
    """The routes the app serves, through the same walker that stamps the OpenAPI security arrays."""
    return _walk_routes(app.routes)


def test_every_endpoint_declares_an_envelope():
    routes = _api_routes(make_app())
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
    """ReDoc renders one sidebar section per tag: every operation carries exactly one resource tag, every tag is declared with a
    description, and x-tagGroups covers every tag so none drop out of the grouped sidebar."""
    app = make_app()
    untagged = [f"{sorted(r.methods or ())} {r.path}" for r in _api_routes(app) if len(r.tags) != 1]
    assert untagged == [], f"Give these operations exactly one resource tag: {untagged}"
    schema = app.openapi()
    used = {str(tag) for r in _api_routes(app) for tag in r.tags}
    declared = {t["name"] for t in schema.get("tags", [])}
    grouped = {tag for group in schema.get("x-tagGroups", []) for tag in group["tags"]}
    assert used == declared, f"Declare every used tag in openapi_tags with a description: {used ^ declared}"
    assert used == grouped, f"List every tag in an x-tagGroups group or it disappears from the ReDoc sidebar: {used ^ grouped}"


def test_operation_ids_are_the_handler_names():
    """Generated clients name every method after operationId, so the ids are the handler names: FastAPI's default bakes the path
    and the verb into each one and turns useListOrgs into useListOrgsV1OrgsGet."""
    app = make_app()
    operation_ids = [op["operationId"] for operations in app.openapi()["paths"].values() for op in operations.values()]
    assert sorted(operation_ids) == sorted(r.name for r in _api_routes(app))
    duplicates = sorted({name for name in operation_ids if operation_ids.count(name) > 1})
    assert duplicates == [], f"Two handlers share a name, so one client method overwrites the other: {duplicates}"


def _nested_models(tp: object, seen: set[type] | None = None) -> set[type]:
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


def test_no_table_model_crosses_the_wire():
    """Rows never serialize directly: every response payload goes through an Out model, so api_hidden fields cannot leak."""
    offenders = sorted(
        f"{model.__name__} via {route.path}"
        for route in _api_routes(make_app())
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
        for route in _api_routes(make_app())
        for field in route.dependant.body_params
        for model in _nested_models(field.field_info.annotation)
        if hasattr(model, "__table__")
    )
    assert offenders == [], f"Accept a RecordCreate[Table] or RecordUpdate[Table] subclass instead: {offenders}"


def test_payloads_are_named_models():
    """Anonymous dict payloads document nothing in OpenAPI; every envelope carries a named model."""
    offenders = []
    for route in _api_routes(make_app()):
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
