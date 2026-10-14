"""Alembic environment: runs migrations over the async engine.

The URL comes from the Alembic config when a caller sets one (tests do), else from settings.
"""

import asyncio

from alembic import context
from hotel_mcp.config import get_settings, normalize_database_url
from hotel_mcp.models import Base
from sqlalchemy import Connection
from sqlalchemy.ext.asyncio import create_async_engine

config = context.config
target_metadata = Base.metadata


def _url() -> str:
    url = config.get_main_option("sqlalchemy.url")
    return normalize_database_url(url) if url else get_settings().database_url


def run_offline() -> None:
    context.configure(url=_url(), target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def _run_sync(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_online() -> None:
    engine = create_async_engine(_url())
    async with engine.connect() as connection:
        await connection.run_sync(_run_sync)
    await engine.dispose()


if context.is_offline_mode():
    run_offline()
else:
    asyncio.run(run_online())
