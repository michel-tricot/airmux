from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import TYPE_CHECKING

import yaml
from cryptography.exceptions import InvalidSignature
from pydantic import ValidationError
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route

from contract import verify_bundle
from data_plane.bundle.config import LocalBundleConfig, RemoteBundleConfig
from data_plane.bundle.holder import BundleHolder
from data_plane.bundle.local import admit_local, run_local_reload
from data_plane.bundle.remote import run_poller
from data_plane.cache import instance_id as cache_instance_id
from data_plane.cache import read_cached_bundle
from data_plane.config import Config, load_config
from data_plane.credentials import CredentialResolver
from data_plane.heartbeat import run_heartbeat
from data_plane.outbox import build_outbox
from data_plane.proxy import complete, messages
from data_plane.runtime import Runtime, runtime_of

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    from starlette.requests import Request

logger = logging.getLogger("data_plane")


async def healthz(_request: Request) -> JSONResponse:
    return JSONResponse({"status": "ok"})


async def readyz(request: Request) -> JSONResponse:
    if runtime_of(request).holder.snapshot is None:
        return JSONResponse({"status": "no bundle"}, status_code=503)
    return JSONResponse({"status": "ready"})


def _configure_dev_logging() -> None:
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(levelname)s:     %(message)s"))
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)


def _load_cached_bundle(bundle_config: RemoteBundleConfig, public_key: Ed25519PublicKey, holder: BundleHolder) -> None:
    try:
        signed = read_cached_bundle(bundle_config.cache_dir)
    except ValidationError:
        logger.exception("cached bundle in %s does not parse, ignoring it", bundle_config.cache_dir)
        return
    if signed is None:
        logger.warning("no cached bundle in %s, serving 503 until one arrives", bundle_config.cache_dir)
        return
    try:
        bundle = verify_bundle(signed, public_key)
    except InvalidSignature:
        logger.exception("cached bundle failed signature verification, ignoring it")
        return
    holder.admit(bundle, bundle_config.staleness_policy, source="cached")


def _start_bundle_source(config: Config, runtime: Runtime) -> list[asyncio.Task[None]]:
    """Start whichever source feeds admit(): the file watcher, or the poller with its siblings.

    A broken local file at boot logs and serves 503 until the reload sees a good one, the same
    contract as a missing cached bundle."""
    bundle_config = config.bundle
    if isinstance(bundle_config, LocalBundleConfig):
        try:
            admit_local(bundle_config, runtime.holder)
        except (OSError, ValidationError, ValueError, yaml.YAMLError):
            logger.exception("local bundle %s did not load, serving 503 until it does", bundle_config.path)
        return [asyncio.create_task(run_local_reload(bundle_config, runtime.holder))]
    public_key = bundle_config.verify_key
    _load_cached_bundle(bundle_config, public_key, runtime.holder)
    if not config.control_plane.url:
        return []
    instance_id = cache_instance_id(bundle_config.cache_dir)
    return [
        asyncio.create_task(run_poller(config.control_plane, bundle_config, runtime.holder, public_key)),
        asyncio.create_task(runtime.outbox.run()),
        asyncio.create_task(run_heartbeat(config, runtime.holder, instance_id)),
    ]


def create_app(config: Config) -> Starlette:
    @contextlib.asynccontextmanager
    async def lifespan(_app: Starlette) -> AsyncIterator[dict[str, Runtime]]:
        if config.dev:
            _configure_dev_logging()
        outbox = build_outbox(config)
        try:
            runtime = Runtime(holder=BundleHolder(), outbox=outbox, credentials=CredentialResolver(config.secrets.build()))
            tasks = _start_bundle_source(config, runtime)
            try:
                yield {"runtime": runtime}
            finally:
                for task in tasks:
                    task.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await task
        finally:
            outbox.close()

    return Starlette(
        routes=[
            Route("/v1/chat/completions", complete, methods=["POST"]),
            Route("/v1/messages", messages, methods=["POST"]),
            Route("/healthz", healthz),
            Route("/readyz", readyz),
        ],
        lifespan=lifespan,
    )


def load_app() -> Starlette:
    return create_app(load_config())
