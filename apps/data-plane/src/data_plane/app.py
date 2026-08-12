from __future__ import annotations

import asyncio
import contextlib
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from cryptography.exceptions import InvalidSignature
from pydantic import ValidationError
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route

from contract import verify_bundle
from data_plane.cache import instance_id as cache_instance_id
from data_plane.cache import read_cached_bundle
from data_plane.config import Config, load_config
from data_plane.credentials import CredentialResolver
from data_plane.heartbeat import run_heartbeat
from data_plane.holder import BundleHolder
from data_plane.outbox import build_outbox
from data_plane.poller import run_poller

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    from starlette.requests import Request

    from data_plane.outbox import EventOutbox

logger = logging.getLogger("data_plane")

holder = BundleHolder()


@dataclass
class AppState:
    config: Config | None = None
    bundle_public_key: Ed25519PublicKey | None = None
    outbox: EventOutbox | None = None
    credentials: CredentialResolver | None = None


state = AppState()


async def healthz(_request: Request) -> JSONResponse:
    return JSONResponse({"status": "ok"})


async def readyz(_request: Request) -> JSONResponse:
    if holder.snapshot is None:
        return JSONResponse({"status": "no bundle"}, status_code=503)
    return JSONResponse({"status": "ready"})


def _configure_dev_logging() -> None:
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(levelname)s:     %(message)s"))
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)


def _load_cached_bundle(config: Config, public_key: Ed25519PublicKey) -> None:
    try:
        signed = read_cached_bundle(config.bundle.cache_dir)
    except ValidationError:
        logger.exception("cached bundle in %s does not parse, ignoring it", config.bundle.cache_dir)
        return
    if signed is None:
        logger.warning("no cached bundle in %s, serving 503 until one arrives", config.bundle.cache_dir)
        return
    try:
        bundle = verify_bundle(signed, public_key)
    except InvalidSignature:
        logger.exception("cached bundle failed signature verification, ignoring it")
        return
    holder.admit(bundle, config.bundle.staleness_policy, source="cached")


def create_app(config_override: Config | None = None) -> Starlette:
    """App factory: production loads the config file, tests inject a constructed Config."""

    @contextlib.asynccontextmanager
    async def lifespan(_app: Starlette) -> AsyncIterator[None]:
        config = config_override or load_config()
        if config.dev:
            _configure_dev_logging()
        state.config = config
        state.outbox = build_outbox(config)
        state.credentials = CredentialResolver(config.secrets.build())
        try:
            state.bundle_public_key = config.bundle.public_key
            _load_cached_bundle(config, state.bundle_public_key)
            instance_id = cache_instance_id(config.bundle.cache_dir)
            tasks = (
                [
                    asyncio.create_task(run_poller(config, holder, state.bundle_public_key)),
                    asyncio.create_task(state.outbox.run()),
                    asyncio.create_task(run_heartbeat(config, holder, instance_id)),
                ]
                if config.control_plane.url
                else []
            )
            try:
                yield
            finally:
                for task in tasks:
                    task.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await task
        finally:
            state.outbox.close()

    return Starlette(
        routes=[
            Route("/healthz", healthz),
            Route("/readyz", readyz),
        ],
        lifespan=lifespan,
    )


app = create_app()
