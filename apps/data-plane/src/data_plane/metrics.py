from __future__ import annotations

import time
from http import HTTPStatus
from typing import TYPE_CHECKING, Literal

import httpx2
from starlette.responses import Response

from airmux_runtime.telemetry import MetricsTelemetry
from data_plane.egress.base import UpstreamProtocolError, UpstreamResponseError, UpstreamStreamError
from data_plane.runtime import runtime_of

if TYPE_CHECKING:
    from datetime import datetime

    from starlette.requests import Request

type HttpOutcome = Literal["success", "rejected", "failed"]
type UpstreamOutcome = Literal["success", "cancelled", "rejected", "timeout", "unreachable", "protocol_error", "provider_error"]
type HttpRequestLabels = tuple[str, str, str, bool]
type BundlePollOutcome = Literal["unchanged", "adopted", "rejected", "failed"]
type CredentialCacheResult = Literal["hit", "miss", "negative_hit", "backend_unavailable"]
type CredentialLoadOutcome = Literal["success", "missing", "backend_unavailable"]
type MeteringAdmissionOutcome = Literal["accepted", "full", "closed"]
type MeteringExportOutcome = Literal["success", "failed"]
type BudgetStateFallback = Literal["missing", "mismatch", "expired"]


class DataPlaneMetrics:
    content_type = MetricsTelemetry.content_type

    def __init__(self) -> None:
        self._budget_state_computed_at = 0.0
        self._bundle_snapshots = 0
        self._bundle_manifest_rejected = 0
        self._bundle_last_adopted = 0.0
        self._metering_writer_queue_depth = 0
        self._metering_writer_queue_capacity = 0
        self._metering_outbox_pending = 0
        self._outbox_oldest_at: float | None = None
        self._telemetry = MetricsTelemetry("airmux-data-plane")
        meter = self._telemetry.meter
        gauge = self._telemetry.observable_gauge
        self._http_requests = meter.create_counter("airmux_data_plane_http_requests", description="HTTP requests completed by the data plane")
        self._http_duration = meter.create_histogram(
            "airmux_data_plane_http_request_duration_seconds", description="Data-plane HTTP request duration"
        )
        self._inflight = meter.create_up_down_counter("airmux_data_plane_inflight_requests", description="Data-plane requests currently in flight")
        self._upstream_attempts = meter.create_counter("airmux_data_plane_upstream_attempts", description="Provider request attempts")
        self._upstream_duration = meter.create_histogram(
            "airmux_data_plane_upstream_attempt_duration_seconds", description="Provider request attempt duration"
        )
        self._credential_cache_requests = meter.create_counter("airmux_data_plane_credential_cache_requests", description="Credential cache requests")
        self._credential_load_duration = meter.create_histogram(
            "airmux_data_plane_credential_load_duration_seconds", description="Credential backend load duration"
        )
        self._bundle_poll = meter.create_counter("airmux_data_plane_bundle_poll", description="Bundle poll outcomes")
        self._budget_state_fallbacks = meter.create_counter(
            "airmux_data_plane_budget_state_fallbacks", description="Budget checks allowed without usable state"
        )
        self._metering_admission = meter.create_counter("airmux_data_plane_metering_admission", description="Metering admission outcomes")
        self._metering_exports = meter.create_counter("airmux_data_plane_metering_exports", description="Metering export outcomes")
        self._metering_export_duration = meter.create_histogram(
            "airmux_data_plane_metering_export_duration_seconds", description="Metering export duration"
        )
        gauge(
            "airmux_data_plane_budget_state_computed_timestamp_seconds",
            "Calculation timestamp of the last accepted budget state",
            lambda: self._budget_state_computed_at,
        )
        gauge("airmux_data_plane_bundle_snapshots", "Accepted bundle snapshots", lambda: self._bundle_snapshots)
        gauge(
            "airmux_data_plane_bundle_manifest_rejected",
            "Whether the newest bundle manifest was rejected",
            lambda: self._bundle_manifest_rejected,
        )
        gauge(
            "airmux_data_plane_bundle_last_adopted_timestamp_seconds",
            "Unix timestamp of the last adopted bundle set",
            lambda: self._bundle_last_adopted,
        )
        gauge(
            "airmux_data_plane_metering_writer_queue_depth",
            "Metering writer queue depth",
            lambda: self._metering_writer_queue_depth,
        )
        gauge(
            "airmux_data_plane_metering_writer_queue_capacity",
            "Metering writer queue capacity",
            lambda: self._metering_writer_queue_capacity,
        )
        gauge(
            "airmux_data_plane_metering_outbox_pending",
            "Durable metering events awaiting export",
            lambda: self._metering_outbox_pending,
        )
        gauge(
            "airmux_data_plane_metering_outbox_oldest_age_seconds",
            "Age of the oldest durable metering event",
            lambda: max(0.0, time.time() - self._outbox_oldest_at) if self._outbox_oldest_at is not None else 0.0,
        )
        for outcome in ("unchanged", "adopted", "rejected", "failed"):
            self._bundle_poll.add(0, {"outcome": outcome})
        for reason in ("missing", "mismatch", "expired"):
            self._budget_state_fallbacks.add(0, {"reason": reason})
        for result in ("hit", "miss", "negative_hit", "backend_unavailable"):
            self._credential_cache_requests.add(0, {"result": result})
        for outcome in ("accepted", "full", "closed"):
            self._metering_admission.add(0, {"outcome": outcome})
        for outcome in ("success", "failed"):
            self._metering_exports.add(0, {"outcome": outcome})

    def observe_inflight(self, route: str, stream: bool, delta: int) -> None:
        self._inflight.add(delta, {"route": route, "stream": str(stream).lower()})

    def observe_http(self, request: HttpRequestLabels, status: int, elapsed: float) -> None:
        route, method, dialect, stream = request
        outcome: HttpOutcome = "success" if status < HTTPStatus.BAD_REQUEST else "rejected" if status < HTTPStatus.INTERNAL_SERVER_ERROR else "failed"
        attributes = {"route": route, "dialect": dialect, "stream": str(stream).lower(), "outcome": outcome}
        self._http_requests.add(1, {**attributes, "method": method, "status_class": f"{status // 100}xx"})
        self._http_duration.record(elapsed, attributes)

    def observe_upstream(self, kind: str, outcome: UpstreamOutcome, started_at: float) -> None:
        attributes = {"egress_kind": kind, "outcome": outcome}
        self._upstream_attempts.add(1, attributes)
        self._upstream_duration.record(time.monotonic() - started_at, attributes)

    def relabel_inflight_stream(self, route: str) -> None:
        self.observe_inflight(route, False, -1)
        self.observe_inflight(route, True, 1)

    def observe_credential_cache(self, result: CredentialCacheResult) -> None:
        self._credential_cache_requests.add(1, {"result": result})

    def observe_credential_load(self, result: CredentialCacheResult, outcome: CredentialLoadOutcome, started_at: float) -> None:
        self.observe_credential_cache(result)
        self._credential_load_duration.record(time.monotonic() - started_at, {"outcome": outcome})

    def observe_budget_state(self, computed_at: float) -> None:
        self._budget_state_computed_at = computed_at

    def observe_budget_state_fallback(self, reason: BudgetStateFallback) -> None:
        self._budget_state_fallbacks.add(1, {"reason": reason})

    def observe_bundle_adopted(self, snapshots: int) -> None:
        self.observe_bundle_poll("adopted")
        self._bundle_snapshots = snapshots
        self._bundle_last_adopted = time.time()

    def observe_bundle_poll(self, outcome: BundlePollOutcome) -> None:
        self._bundle_poll.add(1, {"outcome": outcome})
        if outcome == "rejected":
            self._bundle_manifest_rejected = 1
        elif outcome in {"unchanged", "adopted"}:
            self._bundle_manifest_rejected = 0

    def observe_metering_admission(self, outcome: MeteringAdmissionOutcome) -> None:
        self._metering_admission.add(1, {"outcome": outcome})

    def set_metering_queue(self, depth: int, capacity: int) -> None:
        self._metering_writer_queue_depth = depth
        self._metering_writer_queue_capacity = capacity

    def set_metering_outbox(self, pending: int, oldest_at: datetime | None) -> None:
        self._metering_outbox_pending = pending
        self._outbox_oldest_at = oldest_at.timestamp() if oldest_at is not None else None

    def observe_metering_export(self, outcome: MeteringExportOutcome, started_at: float) -> None:
        attributes = {"outcome": outcome}
        self._metering_exports.add(1, attributes)
        self._metering_export_duration.record(time.monotonic() - started_at, attributes)

    def render(self) -> bytes:
        return self._telemetry.render()

    def shutdown(self) -> None:
        self._telemetry.shutdown()


def upstream_outcome(
    error: UpstreamResponseError | UpstreamProtocolError | UpstreamStreamError | httpx2.HTTPError,
) -> UpstreamOutcome:
    if isinstance(error, httpx2.TimeoutException):
        return "timeout"
    if isinstance(error, httpx2.HTTPError):
        return "unreachable"
    if isinstance(error, UpstreamProtocolError):
        return "protocol_error"
    if isinstance(error, UpstreamResponseError):
        return "rejected" if error.status < HTTPStatus.INTERNAL_SERVER_ERROR else "provider_error"
    return "provider_error"


async def metrics_endpoint(request: Request) -> Response:
    await runtime_of(request).outbox.refresh_metrics()
    metrics: DataPlaneMetrics = request.app.state.metrics
    return Response(metrics.render(), media_type=metrics.content_type)
