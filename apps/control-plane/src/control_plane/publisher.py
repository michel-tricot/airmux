from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy.exc import DBAPIError

from control_plane.compiler import PublicationError, publish_next
from control_plane.db import transaction
from control_plane.models import RuntimeConfiguration

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

logger = logging.getLogger(__name__)


async def run_publisher(factory: async_sessionmaker[AsyncSession]) -> None:
    while True:
        now = datetime.now(tz=UTC)
        try:
            async with transaction(factory, isolation_level="REPEATABLE READ"):
                publication = await publish_next(now)
        except PublicationError as error:
            logger.exception(
                "bundle publication failed for organization %s at configuration revision %d",
                error.org_id,
                error.configuration_revision,
            )
            try:
                async with transaction(factory):
                    await RuntimeConfiguration.record_failure(error.org_id, error.configuration_revision, now)
            except Exception:
                logger.exception("bundle publication failure state could not be recorded")
                await asyncio.sleep(1)
            continue
        except DBAPIError as error:
            if getattr(error.orig, "sqlstate", None) == "40001":
                logger.info("bundle publication snapshot changed; retrying")
                continue
            logger.exception("bundle publisher database failure")
            await asyncio.sleep(1)
            continue
        except Exception:
            logger.exception("bundle publisher failure")
            await asyncio.sleep(1)
            continue
        if publication is None:
            await asyncio.sleep(1)
