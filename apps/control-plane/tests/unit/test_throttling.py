from __future__ import annotations

import asyncio
import re

import httpx
import pytest
from fastapi import FastAPI
from pydantic import ValidationError

from control_plane.metrics import ControlPlaneMetrics
from control_plane.throttling import Allowed, Denied, LocalThrottleBackend, RateLimit, ThrottleConfig, ThrottleMiddleware


async def test_bucket_refills_and_rejects_excess_atomically():
    clock = [0.0]
    backend = LocalThrottleBackend(max_buckets=4, clock=lambda: clock[0])
    limit = RateLimit(burst=2, per_second=0.5)
    decisions = await asyncio.gather(*(backend.consume("login:one", limit) for _ in range(10)))
    assert sum(isinstance(decision, Allowed) for decision in decisions) == 2
    assert all(decision.retry_after == 2 for decision in decisions if isinstance(decision, Denied))
    clock[0] = 2.0
    assert isinstance(await backend.consume("login:one", limit), Allowed)
    assert isinstance(await backend.consume("login:one", limit), Denied)


async def test_full_backend_keeps_active_limits_and_recovers_after_expiry():
    clock = [0.0]
    backend = LocalThrottleBackend(max_buckets=1, clock=lambda: clock[0])
    limit = RateLimit(burst=1, per_second=1)
    assert isinstance(await backend.consume("one", limit), Allowed)
    assert await backend.consume("two", limit) == Denied(retry_after=1, reason="capacity")
    assert await backend.consume("one", limit) == Denied(retry_after=1, reason="quota")
    clock[0] = 1.0
    assert isinstance(await backend.consume("two", limit), Allowed)


@pytest.mark.parametrize("value", [0, -1, float("inf"), float("nan")])
def test_invalid_refill_rates_are_rejected(value):
    with pytest.raises(ValidationError):
        RateLimit(burst=1, per_second=value)


async def test_ip_throttling_precedes_routes_and_separates_operational_traffic():
    app = FastAPI()
    config = ThrottleConfig(api=RateLimit(burst=1, per_second=0.001))
    routes = (
        (re.compile(r"/api/v1/anything(?:-else)?"), frozenset({"GET"}), "api"),
        (re.compile(r"/api/v1/bundles/manifest"), frozenset({"GET"}), "operational"),
    )
    app.add_middleware(ThrottleMiddleware, backend=LocalThrottleBackend(), config=config, routes=routes, metrics=ControlPlaneMetrics())

    @app.get("/{path:path}")
    async def endpoint(path: str):
        return {"path": path}

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        assert (await client.get("/api/v1/anything")).status_code == 200
        denied = await client.get("/api/v1/anything-else", headers={"X-Forwarded-For": "203.0.113.1"})
        assert denied.status_code == 429
        assert int(denied.headers["retry-after"]) > 0
        assert (await client.get("/healthz")).status_code == 200
        assert (await client.get("/api/v1/bundles/manifest")).status_code == 200


async def test_middleware_accepts_an_independent_backend():
    class UnavailableBackend:
        async def consume(self, key: str, limit: RateLimit) -> Allowed | Denied:
            return Denied(retry_after=7, reason="capacity")

    app = FastAPI()
    routes = ((re.compile(r"/api/v1/auth/me"), frozenset({"GET"}), "api"),)
    app.add_middleware(ThrottleMiddleware, backend=UnavailableBackend(), config=ThrottleConfig(), routes=routes, metrics=ControlPlaneMetrics())
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/v1/auth/me")
    assert response.status_code == 503
    assert response.headers["retry-after"] == "7"
