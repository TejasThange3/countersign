"""`hotel-mcp` command line: serve, migrate, seed, reset."""

import argparse
import asyncio
from datetime import date
from pathlib import Path

import uvicorn
from alembic import command
from alembic.config import Config

from hotel_mcp import seed as seed_data
from hotel_mcp.config import get_settings
from hotel_mcp.db import get_engine, get_sessionmaker

MIGRATIONS_DIR = Path(__file__).parent / "migrations"


def alembic_config(url: str | None = None) -> Config:
    """Alembic config built in code so migrations ship inside the package (no alembic.ini)."""
    cfg = Config()
    cfg.set_main_option("script_location", str(MIGRATIONS_DIR))
    if url:
        cfg.set_main_option("sqlalchemy.url", url)
    return cfg


def migrate(url: str | None = None) -> None:
    command.upgrade(alembic_config(url), "head")


async def _load_seed(reset: bool) -> None:
    async with get_sessionmaker()() as session, session.begin():
        if reset:
            await seed_data.reset(session, date.today())
        else:
            await seed_data.seed(session, date.today())
    await get_engine().dispose()


def serve() -> None:
    from hotel_mcp.server import create_app

    settings = get_settings()
    app = create_app(settings.mcp_bearer_token, get_sessionmaker())
    uvicorn.run(app, host=settings.host, port=settings.port, proxy_headers=True)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="hotel-mcp", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("serve", help="run the MCP server on $PORT (streamable HTTP at /mcp)")
    sub.add_parser("migrate", help="apply database migrations (alembic upgrade head)")
    sub.add_parser("seed", help="load synthetic seed data into an empty database")
    reset_cmd = sub.add_parser("reset", help="wipe all rows and reload the seed data")
    reset_cmd.add_argument(
        "--yes", action="store_true", help="confirm: this deletes every row in DATABASE_URL"
    )
    args = parser.parse_args(argv)

    if args.command == "serve":
        serve()
    elif args.command == "migrate":
        migrate()
    elif args.command == "seed":
        asyncio.run(_load_seed(reset=False))
        print("Seeded.")
    elif args.command == "reset":
        if not args.yes:
            parser.error("reset deletes every row in DATABASE_URL; re-run with --yes")
        asyncio.run(_load_seed(reset=True))
        print("Reset to seed state.")
