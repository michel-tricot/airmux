from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from gw_contract import BundleV1


async def compile_bundle(session: AsyncSession, org_id: str) -> BundleV1:
    """Pure function of database state: read every table, build, validate, canonicalize.

    Must be diffable and replayable. expires_at = issued_at + STALENESS_BOUND.
    """
    raise NotImplementedError
