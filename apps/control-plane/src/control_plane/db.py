from __future__ import annotations

from contextlib import asynccontextmanager
from contextvars import ContextVar
from typing import TYPE_CHECKING

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

_session: ContextVar[AsyncSession] = ContextVar("session")

current_actor: ContextVar[str | None] = ContextVar("actor", default=None)


def make_engine(database_url: str) -> AsyncEngine:
    return create_async_engine(database_url)


def make_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


def current_session() -> AsyncSession:
    return _session.get()


@asynccontextmanager
async def transaction(factory: async_sessionmaker[AsyncSession]) -> AsyncIterator[AsyncSession]:
    """One unit of work: the body flushes, commit happens here on success, close rolls back on failure."""
    async with factory() as session:
        token = _session.set(session)
        try:
            yield session
            await session.commit()
        finally:
            _session.reset(token)


@asynccontextmanager
async def standalone_engine(database_url: str) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """Engine and session factory for non-request code (CLI commands, background tasks); disposed on exit.

    Open transaction() per unit of work; use standalone_transaction for the single-transaction case.
    """
    engine = make_engine(database_url)
    try:
        yield make_session_factory(engine)
    finally:
        await engine.dispose()


@asynccontextmanager
async def standalone_transaction(database_url: str) -> AsyncIterator[AsyncSession]:
    """One unit of work for non-request code that needs exactly one transaction."""
    async with standalone_engine(database_url) as factory, transaction(factory) as session:
        yield session
