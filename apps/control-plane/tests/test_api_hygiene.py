from __future__ import annotations

from fastapi.routing import APIRoute
from helpers import setup_control_plane

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
    assert offenders == []


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
