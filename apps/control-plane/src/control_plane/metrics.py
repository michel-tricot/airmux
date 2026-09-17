from __future__ import annotations

import time
from http import HTTPStatus
from typing import TYPE_CHECKING, Literal

from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram, generate_latest
from prometheus_client.exposition import CONTENT_TYPE_LATEST
from starlette.responses import Response

if TYPE_CHECKING:
    from starlette.requests import Request

type HttpOutcome = Literal["success", "rejected", "failed"]
type BundlePublicationOutcome = Literal["success", "failed"]
type ThrottleOutcome = Literal["allowed", "quota", "capacity"]


class ControlPlaneMetrics:
    def __init__(self) -> None:
        self._bundle_pending_since: float | None = None
        self.registry = CollectorRegistry(auto_describe=True)
        self.http_requests = Counter(
            "airmux_control_plane_http_requests_total",
            "HTTP requests completed by the control plane",
            ("route", "method", "outcome", "status_class"),
            registry=self.registry,
        )
        self.http_duration = Histogram(
            "airmux_control_plane_http_request_duration_seconds",
            "Control-plane HTTP request duration",
            ("route", "method", "outcome"),
            registry=self.registry,
        )
        self.inflight = Gauge(
            "airmux_control_plane_inflight_requests", "Control-plane requests currently in flight", ("route",), registry=self.registry
        )
        self.throttle_decisions = Counter("airmux_control_plane_throttle_decisions_total", "Throttle decisions", ("outcome",), registry=self.registry)
        self.event_ingest = Counter("airmux_control_plane_event_ingest_total", "Usage event ingest outcomes", ("outcome",), registry=self.registry)
        self.event_ingest_duration = Histogram(
            "airmux_control_plane_event_ingest_duration_seconds", "Usage event ingest duration", ("outcome",), registry=self.registry
        )
        self.bundle_publications = Counter(
            "airmux_control_plane_bundle_publications_total", "Bundle publication outcomes", ("outcome",), registry=self.registry
        )
        self.bundle_publication_pending = Gauge(
            "airmux_control_plane_bundle_publication_pending", "Pending bundle publications", registry=self.registry
        )
        self.bundle_publication_oldest_age = Gauge(
            "airmux_control_plane_bundle_publication_oldest_age_seconds",
            "Time this process has continuously observed pending bundle publication work",
            registry=self.registry,
        )
        for outcome in ("allowed", "quota", "capacity"):
            self.throttle_decisions.labels(outcome).inc(0)
        for outcome in ("success", "rejected", "failed"):
            self.event_ingest.labels(outcome).inc(0)
            self.bundle_publications.labels(outcome).inc(0)

    def observe_http(self, route: str, method: str, status: int, elapsed: float) -> None:
        outcome: HttpOutcome = "success" if status < HTTPStatus.BAD_REQUEST else "rejected" if status < HTTPStatus.INTERNAL_SERVER_ERROR else "failed"
        self.http_requests.labels(route, method, outcome, f"{status // 100}xx").inc()
        self.http_duration.labels(route, method, outcome).observe(elapsed)

    def observe_throttle(self, outcome: ThrottleOutcome) -> None:
        self.throttle_decisions.labels(outcome).inc()

    def observe_bundle_publication(self, outcome: BundlePublicationOutcome) -> None:
        self.bundle_publications.labels(outcome).inc()

    def observe_bundle_backlog(self, pending: int) -> None:
        now = time.monotonic()
        if pending == 0:
            self._bundle_pending_since = None
        elif self._bundle_pending_since is None:
            self._bundle_pending_since = now
        self.bundle_publication_pending.set(pending)
        self.bundle_publication_oldest_age.set(0 if self._bundle_pending_since is None else now - self._bundle_pending_since)


async def metrics_endpoint(request: Request) -> Response:
    return Response(generate_latest(request.app.state.metrics.registry), media_type=CONTENT_TYPE_LATEST)
