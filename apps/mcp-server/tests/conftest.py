"""Shared fixtures. Unit tests run on SQLite (no Docker); integration tests use Postgres."""

from collections.abc import AsyncIterator
from datetime import date

import pytest
from hotel_mcp.models import Base
from hotel_mcp.seed import seed
from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

# A fixed "today" so seed data and date validation are reproducible.
TODAY = date(2026, 10, 14)


def _enable_sqlite_foreign_keys(engine: AsyncEngine) -> None:
    # SQLite ignores ON DELETE CASCADE unless foreign keys are switched on per connection.
    @event.listens_for(engine.sync_engine, "connect")
    def _on_connect(dbapi_connection, _record) -> None:  # type: ignore[no-untyped-def]
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


@pytest.fixture
async def engine(tmp_path) -> AsyncIterator[AsyncEngine]:  # type: ignore[no-untyped-def]
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'hotel.db'}")
    _enable_sqlite_foreign_keys(engine)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture
async def sessionmaker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session, session.begin():
        await seed(session, TODAY)
    return maker


@pytest.fixture
async def session(sessionmaker: async_sessionmaker[AsyncSession]) -> AsyncIterator[AsyncSession]:
    async with sessionmaker() as session, session.begin():
        yield session
