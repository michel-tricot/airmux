from __future__ import annotations

import asyncio
import hashlib
import math
import re
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, Protocol, cast

from fastapi.routing import APIRoute
from pydantic import BaseModel, ConfigDict, Field
from starlette.responses import JSONResponse

if TYPE_CHECKING:
    from collections.abc import Callable
    from re import Pattern
    from uuid import UUID

    from fastapi import APIRouter
    from starlette.requests import Request
    from starlette.types import ASGIApp, Receive, Scope, Send

    from control_plane.metrics import ControlPlaneMetrics


class RateLimit(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)

    burst: int = Field(gt=0)
    per_second: float = Field(gt=0)


class ThrottleConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    api: RateLimit = RateLimit(burst=120, per_second=20)
    authentication: RateLimit = RateLimit(burst=5, per_second=1 / 6)
    account: RateLimit = RateLimit(burst=5, per_second=1 / 12)
    cli: RateLimit = RateLimit(burst=10, per_second=2)
    operational: RateLimit = RateLimit(burst=1000, per_second=100)
    max_buckets: int = Field(default=10000, gt=0)
    password_workers: int = Field(default=2, gt=0, le=32)
    password_queue: int = Field(default=8, ge=0, le=256)


@dataclass(frozen=True)
class Allowed:
    pass


@dataclass(frozen=True)
class Denied:
    retry_after: int
    reason: Literal["quota", "capacity"]


class ThrottleBackend(Protocol):
    async def consume(self, key: str, limit: RateLimit) -> Allowed | Denied: ...


@dataclass(frozen=True)
class _Bucket:
    tokens: float
    updated_at: float
    expires_at: float


class LocalThrottleBackend:
    def __init__(self, *, max_buckets: int = 10000, clock: Callable[[], float] = time.monotonic) -> None:
        if max_buckets < 1:
            message = "Throttle capacity must be positive"
            raise ValueError(message)
        self._max_buckets = max_buckets
        self._clock = clock
        self._buckets: dict[str, _Bucket] = {}
        self._lock = asyncio.Lock()
        self._next_cleanup = 0.0

    async def consume(self, key: str, limit: RateLimit) -> Allowed | Denied:
        async with self._lock:
            now = self._clock()
            if now >= self._next_cleanup:
                self._buckets = {name: bucket for name, bucket in self._buckets.items() if bucket.expires_at > now}
                self._next_cleanup = now + 1
            bucket = self._buckets.get(key)
            if bucket is None and len(self._buckets) >= self._max_buckets:
                return Denied(retry_after=1, reason="capacity")
            tokens = min(limit.burst, bucket.tokens + max(0, now - bucket.updated_at) * limit.per_second) if bucket else float(limit.burst)
            if tokens < 1:
                return Denied(retry_after=max(1, math.ceil((1 - tokens) / limit.per_second)), reason="quota")
            tokens -= 1
            self._buckets[key] = _Bucket(tokens=tokens, updated_at=now, expires_at=now + (limit.burst - tokens) / limit.per_second)
            return Allowed()


type TrafficGroup = Literal["api", "authentication", "cli", "operational"]
type ThrottleRoute = tuple["Pattern[str]", frozenset[str], TrafficGroup]


def compile_routes(routers: tuple[APIRouter, ...]) -> tuple[ThrottleRoute, ...]:
    return tuple(
        (re.compile(f"^/api/v1{route.path_regex.pattern.removeprefix('^')}"), frozenset(route.methods or ()), cast("TrafficGroup", groups[0]))
        for router in routers
        for route in router.routes
        if isinstance(route, APIRoute)
        if (
            groups := [group for dependency in route.dependant.dependencies if (group := getattr(dependency.call, "traffic_group", None)) is not None]
        )
    )


def quota(config: ThrottleConfig, group: TrafficGroup) -> RateLimit:
    return getattr(config, group)


def throttle_key(group: str, identity: str) -> str:
    return f"{group}:{hashlib.sha256(identity.encode()).hexdigest()}"


def denied_response(decision: Denied) -> JSONResponse:
    return JSONResponse(
        status_code=429 if decision.reason == "quota" else 503,
        content={"detail": "Too many requests" if decision.reason == "quota" else "Authentication service is busy"},
        headers={"Retry-After": str(decision.retry_after), "Cache-Control": "no-store"},
    )


class ThrottleMiddleware:
    def __init__(
        self,
        app: ASGIApp,
        *,
        backend: ThrottleBackend,
        config: ThrottleConfig,
        routes: tuple[ThrottleRoute, ...],
        metrics: ControlPlaneMetrics,
    ) -> None:
        self.app = app
        self.backend = backend
        self.config = config
        self.routes = routes
        self.metrics = metrics

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and scope["path"].startswith("/api/v1/"):
            method = scope["method"]
            group = next((group for pattern, methods, group in self.routes if method in methods and pattern.fullmatch(scope["path"])), "api")
            scope.setdefault("state", {})["traffic_group"] = group
            client = scope.get("client")
            identity = client[0] if client else "unknown"
            decision = await self.backend.consume(throttle_key(f"ip:{group}", identity), quota(self.config, group))
            self.metrics.throttle_decisions.labels(decision.reason if isinstance(decision, Denied) else "allowed").inc()
            if isinstance(decision, Denied):
                await denied_response(decision)(scope, receive, send)
                return
        await self.app(scope, receive, send)


class ThrottledError(Exception):
    def __init__(self, decision: Denied) -> None:
        self.decision = decision


async def check_identity(request: Request, identity: UUID) -> None:
    group = cast("TrafficGroup", request.state.traffic_group)
    decision = await request.app.state.throttle_backend.consume(
        throttle_key(f"principal:{group}", str(identity)), quota(request.app.state.settings.throttling, group)
    )
    request.app.state.metrics.throttle_decisions.labels(decision.reason if isinstance(decision, Denied) else "allowed").inc()
    if isinstance(decision, Denied):
        raise ThrottledError(decision)


async def check_account(request: Request, email: str) -> None:
    client = request.client.host if request.client else "unknown"
    decision = await request.app.state.throttle_backend.consume(
        throttle_key("account", f"{client}:{email.strip().casefold()}"), request.app.state.settings.throttling.account
    )
    request.app.state.metrics.throttle_decisions.labels(decision.reason if isinstance(decision, Denied) else "allowed").inc()
    if isinstance(decision, Denied):
        raise ThrottledError(decision)
