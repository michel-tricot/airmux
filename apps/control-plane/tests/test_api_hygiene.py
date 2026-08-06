from __future__ import annotations

from typing import get_args

from fastapi.routing import APIRoute
from helpers import setup_control_plane
from pydantic import BaseModel

from control_plane.schemas import Envelope


def _api_routes(app) -> list[APIRoute]:
    """All routes the app serves, reaching through FastAPI's lazily included routers at any depth."""

    def walk(routes) -> list[APIRoute]:
        routers = (getattr(r, "original_router", None) for r in routes)
        nested = [route for router in routers if router is not None for route in walk(router.routes)]
        return [*(r for r in routes if isinstance(r, APIRoute)), *nested]

    return walk(app.routes)


def test_every_endpoint_declares_an_envelope(tmp_path):
    cp = setup_control_plane(tmp_path)
    routes = _api_routes(cp.app)
    assert routes
    offenders = [
        f"{sorted(r.methods or ())} {r.path}"
        for r in routes
        if r.response_model is None or not (isinstance(r.response_model, type) and issubclass(r.response_model, Envelope))
    ]
    assert offenders == [], (
        f"Every endpoint responds {{'data': ...}}: annotate these with `-> Envelope[YourOut]` and return Envelope(data=...): {offenders}"
    )


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


def test_no_table_model_crosses_the_wire(tmp_path):
    """Rows never serialize directly: every response payload goes through an Out model, so api_hidden fields cannot leak."""
    cp = setup_control_plane(tmp_path)
    offenders = sorted(
        f"{model.__name__} via {route.path}"
        for route in _api_routes(cp.app)
        for model in _nested_models(route.response_model)
        if hasattr(model, "__table__")
    )
    assert offenders == [], (
        f"Table rows must not serialize directly, or api_hidden fields leak. Serve an ApiOut subclass (XOut.model_validate(row)) and register it "
        f"in test_api_parity.RESOURCES: {offenders}"
    )


def test_response_schemas_are_pure_envelopes(tmp_path):
    cp = setup_control_plane(tmp_path)
    spec = cp.app.openapi()
    offenders = []
    for path, ops in spec["paths"].items():
        for method, op in ops.items():
            schema = op["responses"]["200"]["content"]["application/json"]["schema"]
            if "$ref" in schema:
                schema = spec["components"]["schemas"][schema["$ref"].rsplit("/", 1)[1]]
            if set(schema.get("properties", {})) != {"data"}:
                offenders.append(f"{method.upper()} {path}")
    assert offenders == []
