from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy.exc import DBAPIError

from control_plane.compiler import PublicationError, publish_next
from control_plane.db import transaction
from control_plane.models import BundleState

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from control_plane.metrics import ControlPlaneMetrics

logger = logging.getLogger(__name__)


async def run_publisher(factory: async_sessionmaker[AsyncSession], metrics: ControlPlaneMetrics) -> None:
    while True:
        now = datetime.now(tz=UTC)
        try:
            async with transaction(factory, isolation_level="REPEATABLE READ"):
                publication = await publish_next(now)
                pending = await BundleState.pending_count()
        except PublicationError as error:
            metrics.observe_bundle_publication("failed")
            logger.exception(
                "bundle publication failed for organization %s at generations %d/%d",
                error.org_id,
                error.generations.global_,
                error.generations.org,
            )
            try:
                async with transaction(factory):
                    await BundleState.record_failure(error.org_id, error.generations, now)
                    pending = await BundleState.pending_count()
                metrics.observe_bundle_backlog(pending)
            except Exception:
                logger.exception("bundle publication failure state could not be recorded")
                await asyncio.sleep(1)
            continue
        except DBAPIError as error:
            if getattr(error.orig, "sqlstate", None) == "40001":
                logger.info("bundle publication snapshot changed; retrying")
                continue
            metrics.observe_bundle_publication("failed")
            logger.exception("bundle publisher database failure")
            await asyncio.sleep(1)
            continue
        except Exception:
            metrics.observe_bundle_publication("failed")
            logger.exception("bundle publisher failure")
            await asyncio.sleep(1)
            continue
        metrics.observe_bundle_backlog(pending)
        if publication is None:
            await asyncio.sleep(1)
        else:
            metrics.observe_bundle_publication("success")
