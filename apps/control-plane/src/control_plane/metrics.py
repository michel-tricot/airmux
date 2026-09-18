from __future__ import annotations

import time
from http import HTTPStatus
from typing import TYPE_CHECKING, Literal

from starlette.responses import Response

from airmux_runtime.telemetry import MetricsTelemetry

if TYPE_CHECKING:
    from starlette.requests import Request

type HttpOutcome = Literal["success", "rejected", "failed"]
type BundlePublicationOutcome = Literal["success", "failed"]
type ThrottleOutcome = Literal["allowed", "quota", "capacity"]


class ControlPlaneMetrics:
    content_type = MetricsTelemetry.content_type

    def __init__(self) -> None:
        self._bundle_publication_pending = 0
        self._bundle_publication_oldest_age = 0.0
        self._bundle_pending_since: float | None = None
        self._telemetry = MetricsTelemetry("airmux-control-plane")
        meter = self._telemetry.meter
        gauge = self._telemetry.observable_gauge
        self._http_requests = meter.create_counter("airmux_control_plane_http_requests", description="HTTP requests completed by the control plane")
        self._http_duration = meter.create_histogram(
            "airmux_control_plane_http_request_duration_seconds", description="Control-plane HTTP request duration"
        )
        self._inflight = meter.create_up_down_counter(
            "airmux_control_plane_inflight_requests", description="Control-plane requests currently in flight"
        )
        self._throttle_decisions = meter.create_counter("airmux_control_plane_throttle_decisions", description="Throttle decisions")
        self._event_ingest = meter.create_counter("airmux_control_plane_event_ingest", description="Usage event ingest outcomes")
        self._event_ingest_duration = meter.create_histogram(
            "airmux_control_plane_event_ingest_duration_seconds", description="Usage event ingest duration"
        )
        self._bundle_publications = meter.create_counter("airmux_control_plane_bundle_publications", description="Bundle publication outcomes")
        gauge(
            "airmux_control_plane_bundle_publication_pending",
            "Pending bundle publications",
            lambda: self._bundle_publication_pending,
        )
        gauge(
            "airmux_control_plane_bundle_publication_oldest_age_seconds",
            "Time this process has continuously observed pending bundle publication work",
            lambda: self._bundle_publication_oldest_age,
        )
        for outcome in ("allowed", "quota", "capacity"):
            self._throttle_decisions.add(0, {"outcome": outcome})
        for outcome in ("success", "rejected", "failed"):
            self._event_ingest.add(0, {"outcome": outcome})
            self._bundle_publications.add(0, {"outcome": outcome})

    def observe_inflight(self, route: str, delta: int) -> None:
        self._inflight.add(delta, {"route": route})

    def observe_http(self, route: str, method: str, status: int, elapsed: float) -> None:
        outcome: HttpOutcome = "success" if status < HTTPStatus.BAD_REQUEST else "rejected" if status < HTTPStatus.INTERNAL_SERVER_ERROR else "failed"
        attributes = {"route": route, "method": method, "outcome": outcome}
        self._http_requests.add(1, {**attributes, "status_class": f"{status // 100}xx"})
        self._http_duration.record(elapsed, attributes)

    def observe_event_ingest(self, outcome: HttpOutcome, elapsed: float) -> None:
        attributes = {"outcome": outcome}
        self._event_ingest.add(1, attributes)
        self._event_ingest_duration.record(elapsed, attributes)

    def observe_throttle(self, outcome: ThrottleOutcome) -> None:
        self._throttle_decisions.add(1, {"outcome": outcome})

    def observe_bundle_publication(self, outcome: BundlePublicationOutcome) -> None:
        self._bundle_publications.add(1, {"outcome": outcome})

    def observe_bundle_backlog(self, pending: int) -> None:
        now = time.monotonic()
        if pending == 0:
            self._bundle_pending_since = None
        elif self._bundle_pending_since is None:
            self._bundle_pending_since = now
        self._bundle_publication_pending = pending
        self._bundle_publication_oldest_age = 0 if self._bundle_pending_since is None else now - self._bundle_pending_since

    def render(self) -> bytes:
        return self._telemetry.render()

    def shutdown(self) -> None:
        self._telemetry.shutdown()


async def metrics_endpoint(request: Request) -> Response:
    metrics: ControlPlaneMetrics = request.app.state.metrics
    return Response(metrics.render(), media_type=metrics.content_type)
