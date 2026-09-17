from __future__ import annotations

import time
from http import HTTPStatus
from typing import TYPE_CHECKING, Literal

import httpx
from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram, generate_latest
from prometheus_client.exposition import CONTENT_TYPE_LATEST
from starlette.responses import Response

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


class DataPlaneMetrics:
    def __init__(self) -> None:
        self._outbox_oldest_at: float | None = None
        self.registry = CollectorRegistry(auto_describe=True)
        self.http_requests = Counter(
            "airmux_data_plane_http_requests_total",
            "HTTP requests completed by the data plane",
            ("route", "method", "dialect", "stream", "outcome", "status_class"),
            registry=self.registry,
        )
        self.http_duration = Histogram(
            "airmux_data_plane_http_request_duration_seconds",
            "Data-plane HTTP request duration",
            ("route", "dialect", "stream", "outcome"),
            registry=self.registry,
        )
        self.inflight = Gauge(
            "airmux_data_plane_inflight_requests",
            "Data-plane requests currently in flight",
            ("route", "stream"),
            registry=self.registry,
        )
        self.upstream_attempts = Counter(
            "airmux_data_plane_upstream_attempts_total",
            "Provider request attempts",
            ("egress_kind", "outcome"),
            registry=self.registry,
        )
        self.upstream_duration = Histogram(
            "airmux_data_plane_upstream_attempt_duration_seconds",
            "Provider request attempt duration",
            ("egress_kind", "outcome"),
            registry=self.registry,
        )
        self.credential_cache_requests = Counter(
            "airmux_data_plane_credential_cache_requests_total",
            "Credential cache requests",
            ("result",),
            registry=self.registry,
        )
        self.credential_load_duration = Histogram(
            "airmux_data_plane_credential_load_duration_seconds",
            "Credential backend load duration",
            ("outcome",),
            registry=self.registry,
        )
        self.bundle_poll = Counter(
            "airmux_data_plane_bundle_poll_total",
            "Bundle poll outcomes",
            ("outcome",),
            registry=self.registry,
        )
        self.bundle_snapshots = Gauge(
            "airmux_data_plane_bundle_snapshots",
            "Accepted bundle snapshots",
            registry=self.registry,
        )
        self.bundle_manifest_rejected = Gauge(
            "airmux_data_plane_bundle_manifest_rejected",
            "Whether the newest bundle manifest was rejected",
            registry=self.registry,
        )
        self.bundle_last_adopted = Gauge(
            "airmux_data_plane_bundle_last_adopted_timestamp_seconds",
            "Unix timestamp of the last adopted bundle set",
            registry=self.registry,
        )
        self.metering_writer_queue_depth = Gauge(
            "airmux_data_plane_metering_writer_queue_depth", "Metering writer queue depth", registry=self.registry
        )
        self.metering_writer_queue_capacity = Gauge(
            "airmux_data_plane_metering_writer_queue_capacity", "Metering writer queue capacity", registry=self.registry
        )
        self.metering_admission = Counter(
            "airmux_data_plane_metering_admission_total", "Metering admission outcomes", ("outcome",), registry=self.registry
        )
        self.metering_outbox_pending = Gauge(
            "airmux_data_plane_metering_outbox_pending", "Durable metering events awaiting export", registry=self.registry
        )
        self.metering_outbox_oldest_age = Gauge(
            "airmux_data_plane_metering_outbox_oldest_age_seconds", "Age of the oldest durable metering event", registry=self.registry
        )
        self.metering_exports = Counter("airmux_data_plane_metering_exports_total", "Metering export outcomes", ("outcome",), registry=self.registry)
        self.metering_export_duration = Histogram(
            "airmux_data_plane_metering_export_duration_seconds", "Metering export duration", ("outcome",), registry=self.registry
        )
        self.metering_outbox_oldest_age.set_function(
            lambda: max(0.0, time.time() - self._outbox_oldest_at) if self._outbox_oldest_at is not None else 0.0
        )
        for outcome in ("unchanged", "adopted", "rejected", "failed"):
            self.bundle_poll.labels(outcome).inc(0)
        for result in ("hit", "miss", "negative_hit", "backend_unavailable"):
            self.credential_cache_requests.labels(result).inc(0)
        for outcome in ("accepted", "full", "closed"):
            self.metering_admission.labels(outcome).inc(0)
        for outcome in ("success", "failed"):
            self.metering_exports.labels(outcome).inc(0)

    def observe_http(self, request: HttpRequestLabels, status: int, elapsed: float) -> None:
        route, method, dialect, stream = request
        outcome: HttpOutcome = "success" if status < HTTPStatus.BAD_REQUEST else "rejected" if status < HTTPStatus.INTERNAL_SERVER_ERROR else "failed"
        stream_label = str(stream).lower()
        self.http_requests.labels(route, method, dialect, stream_label, outcome, f"{status // 100}xx").inc()
        self.http_duration.labels(route, dialect, stream_label, outcome).observe(elapsed)

    def observe_upstream(self, kind: str, outcome: UpstreamOutcome, started_at: float) -> None:
        self.upstream_attempts.labels(kind, outcome).inc()
        self.upstream_duration.labels(kind, outcome).observe(time.monotonic() - started_at)

    def relabel_inflight_stream(self, route: str) -> None:
        self.inflight.labels(route, "false").dec()
        self.inflight.labels(route, "true").inc()

    def observe_credential_cache(self, result: CredentialCacheResult) -> None:
        self.credential_cache_requests.labels(result).inc()

    def observe_credential_load(self, result: CredentialCacheResult, outcome: CredentialLoadOutcome, started_at: float) -> None:
        self.observe_credential_cache(result)
        self.credential_load_duration.labels(outcome).observe(time.monotonic() - started_at)

    def observe_bundle_adopted(self, snapshots: int) -> None:
        self.observe_bundle_poll("adopted")
        self.bundle_snapshots.set(snapshots)
        self.bundle_last_adopted.set(time.time())

    def observe_bundle_poll(self, outcome: BundlePollOutcome) -> None:
        self.bundle_poll.labels(outcome).inc()
        if outcome == "rejected":
            self.bundle_manifest_rejected.set(1)
        elif outcome in {"unchanged", "adopted"}:
            self.bundle_manifest_rejected.set(0)

    def observe_metering_admission(self, outcome: MeteringAdmissionOutcome) -> None:
        self.metering_admission.labels(outcome).inc()

    def set_metering_queue(self, depth: int, capacity: int) -> None:
        self.metering_writer_queue_depth.set(depth)
        self.metering_writer_queue_capacity.set(capacity)

    def set_metering_outbox(self, pending: int, oldest_at: datetime | None) -> None:
        self.metering_outbox_pending.set(pending)
        self._outbox_oldest_at = oldest_at.timestamp() if oldest_at is not None else None

    def observe_metering_export(self, outcome: MeteringExportOutcome, started_at: float) -> None:
        self.metering_exports.labels(outcome).inc()
        self.metering_export_duration.labels(outcome).observe(time.monotonic() - started_at)


def upstream_outcome(
    error: UpstreamResponseError | UpstreamProtocolError | UpstreamStreamError | httpx.HTTPError,
) -> UpstreamOutcome:
    if isinstance(error, httpx.TimeoutException):
        return "timeout"
    if isinstance(error, httpx.HTTPError):
        return "unreachable"
    if isinstance(error, UpstreamProtocolError):
        return "protocol_error"
    if isinstance(error, UpstreamResponseError):
        return "rejected" if error.status < HTTPStatus.INTERNAL_SERVER_ERROR else "provider_error"
    return "provider_error"


async def metrics_endpoint(request: Request) -> Response:
    await runtime_of(request).outbox.refresh_metrics()
    return Response(generate_latest(request.app.state.metrics.registry), media_type=CONTENT_TYPE_LATEST)
