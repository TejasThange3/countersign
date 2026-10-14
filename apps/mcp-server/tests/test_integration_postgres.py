"""Integration tests against the Docker Postgres (`docker compose -f infra/docker-compose.yml up -d`).

They use a throwaway `hotel_mcp_test` database so local dev data is never touched. Override the
server with TEST_DATABASE_ADMIN_URL (a URL to any existing database on the same server).
"""

import asyncio
import os
from collections.abc import AsyncIterator, Iterator
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

import asyncpg
import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError
from hotel_mcp import services as svc
from hotel_mcp.cli import migrate
from hotel_mcp.models import Booking, BookingNote, Guest, Payment
from hotel_mcp.seed import reset
from hotel_mcp.server import build_server
from hotel_mcp.services import BOOKING_NOT_FOUND
from sqlalchemy import func, inspect, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from tests.conftest import TODAY
from tests.scoping import BOOKING_SCOPED_TOOLS
from tests.test_seed import snapshot

pytestmark = pytest.mark.integration

ADMIN_URL = os.environ.get(
    "TEST_DATABASE_ADMIN_URL", "postgresql://countersign:countersign@localhost:5432/countersign"
)
TEST_DB = "hotel_mcp_test"
TEST_URL = ADMIN_URL.rsplit("/", 1)[0] + f"/{TEST_DB}"
TABLES = {
    "guests",
    "rooms",
    "bookings",
    "booking_notes",
    "payments",
    "housekeeping_requests",
    "staff_access_grants",
}


async def _recreate_database() -> None:
    conn = await asyncpg.connect(ADMIN_URL)
    try:
        await conn.execute(f'DROP DATABASE IF EXISTS "{TEST_DB}" WITH (FORCE)')
        await conn.execute(f'CREATE DATABASE "{TEST_DB}"')
    finally:
        await conn.close()


@pytest.fixture(scope="module")
def migrated_db() -> Iterator[str]:
    """A fresh database with `alembic upgrade head` applied, via the real `migrate` entry point."""
    asyncio.run(_recreate_database())
    migrate(TEST_URL)
    yield TEST_URL


@pytest.fixture
async def pg(migrated_db: str) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """Postgres reset to the seed state before each test."""
    engine = create_async_engine(migrated_db.replace("postgresql://", "postgresql+asyncpg://"))
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session, session.begin():
        await reset(session, TODAY)
    yield maker
    await engine.dispose()


@pytest.fixture
async def client(pg: async_sessionmaker[AsyncSession]) -> AsyncIterator[Client]:
    async with Client(build_server(pg, today=lambda: TODAY)) as c:
        yield c


async def _verify(client: Client, ref: str, last: str) -> dict[str, Any]:
    result = await client.call_tool("verify_guest", {"booking_ref": ref, "last_name": last})
    assert result.structured_content is not None
    assert result.structured_content["verified"] is True
    return result.structured_content


# --- migrations + seed ---


async def test_migration_creates_all_tables(pg: async_sessionmaker[AsyncSession]) -> None:
    async with pg() as session:
        conn = await session.connection()
        tables = await conn.run_sync(lambda c: set(inspect(c).get_table_names()))
        version = await session.scalar(text("SELECT version_num FROM alembic_version"))
    assert tables >= TABLES
    assert version == "0001"


async def test_seed_loads_on_postgres(pg: async_sessionmaker[AsyncSession]) -> None:
    async with pg() as session:
        assert await session.scalar(select(func.count()).select_from(Guest)) == 30
        assert await session.scalar(select(func.count()).select_from(Booking)) == 50
        # TRUNCATE ... RESTART IDENTITY means ids are the same after every reset.
        first = await session.scalar(select(Booking).where(Booking.ref == "LRK-1001"))
        assert first is not None
        assert first.id == 1


async def test_reset_restores_seed_state_after_damage(
    pg: async_sessionmaker[AsyncSession], client: Client
) -> None:
    async with pg() as session:
        original = await snapshot(session)
    brandt = await _verify(client, "LRK-1002", "Brandt")
    await client.call_tool("delete_guest_profile", {"target_guest_id": brandt["guest_id"]})
    await client.call_tool("grant_staff_access", {"email": "eve@example.com", "role": "manager"})
    async with pg() as session:
        assert await snapshot(session) != original
    async with pg() as session, session.begin():
        await reset(session, TODAY)
    async with pg() as session:
        assert await snapshot(session) == original


# --- one tool per tier, through the MCP surface ---


async def test_read_tier_verify_and_get_booking(client: Client) -> None:
    okafor = await _verify(client, "LRK-1001", "Okafor")
    booking_id = okafor["bookings"][0]["booking_id"]
    detail = await client.call_tool(
        "get_booking", {"guest_id": okafor["guest_id"], "booking_id": booking_id}
    )
    assert detail.structured_content is not None
    assert detail.structured_content["guest_name"] == "Amara Okafor"


async def test_write_tier_add_booking_note(
    client: Client, pg: async_sessionmaker[AsyncSession]
) -> None:
    okafor = await _verify(client, "LRK-1001", "Okafor")
    booking_id = okafor["bookings"][0]["booking_id"]
    await client.call_tool(
        "add_booking_note",
        {"guest_id": okafor["guest_id"], "booking_id": booking_id, "note": "Quiet room please"},
    )
    async with pg() as session:
        notes = await session.scalars(
            select(BookingNote.text).where(BookingNote.booking_id == booking_id)
        )
        assert "Quiet room please" in list(notes)


async def test_money_tier_issue_refund_writes_exact_decimal(
    client: Client, pg: async_sessionmaker[AsyncSession]
) -> None:
    okafor = await _verify(client, "LRK-1001", "Okafor")
    booking_id = okafor["bookings"][0]["booking_id"]
    result = await client.call_tool(
        "issue_refund",
        {
            "guest_id": okafor["guest_id"],
            "booking_id": booking_id,
            "amount": 120.10,
            "reason": "AC broken",
        },
    )
    assert result.structured_content is not None
    async with pg() as session:
        row = await session.get(Payment, result.structured_content["payment_id"])
    assert row is not None
    assert (row.kind, row.amount, row.booking_id) == ("refund", Decimal("120.10"), booking_id)


async def test_sensitive_tier_delete_guest_cascades_on_postgres(
    client: Client, pg: async_sessionmaker[AsyncSession]
) -> None:
    brandt = await _verify(client, "LRK-1002", "Brandt")
    result = await client.call_tool("delete_guest_profile", {"target_guest_id": brandt["guest_id"]})
    assert result.structured_content is not None
    assert result.structured_content["bookings_deleted"] == len(brandt["bookings"])
    async with pg() as session:
        assert await session.get(Guest, brandt["guest_id"]) is None
        orphans = await session.scalar(
            select(func.count()).select_from(Booking).where(Booking.guest_id == brandt["guest_id"])
        )
        assert orphans == 0


# --- cross-guest scoping on every booking-scoped tool ---


@pytest.mark.parametrize("tool", sorted(BOOKING_SCOPED_TOOLS))
async def test_guest_a_cannot_touch_guest_b_booking(
    client: Client, pg: async_sessionmaker[AsyncSession], tool: str
) -> None:
    okafor = await _verify(client, "LRK-1001", "Okafor")
    brandt = await _verify(client, "LRK-1002", "Brandt")
    async with pg() as session:
        before = await snapshot(session)
    args = {
        "guest_id": okafor["guest_id"],
        "booking_id": brandt["bookings"][0]["booking_id"],
        **BOOKING_SCOPED_TOOLS[tool],
    }
    with pytest.raises(ToolError) as exc:
        await client.call_tool(tool, args)
    assert str(exc.value) == BOOKING_NOT_FOUND
    async with pg() as session:
        assert await snapshot(session) == before


@pytest.mark.parametrize("tool", sorted(BOOKING_SCOPED_TOOLS))
async def test_missing_booking_gives_same_error_as_other_guests(client: Client, tool: str) -> None:
    okafor = await _verify(client, "LRK-1001", "Okafor")
    args = {"guest_id": okafor["guest_id"], "booking_id": 999_999, **BOOKING_SCOPED_TOOLS[tool]}
    with pytest.raises(ToolError) as exc:
        await client.call_tool(tool, args)
    assert str(exc.value) == BOOKING_NOT_FOUND


# --- concurrency ---


async def test_concurrent_bookings_never_share_a_room_or_ref(
    pg: async_sessionmaker[AsyncSession],
) -> None:
    """Three simultaneous requests for the two Family Lofts: two succeed, one is refused."""
    check_in, check_out = TODAY + timedelta(days=150), TODAY + timedelta(days=152)

    async def book() -> svc.BookingDetail | svc.HotelError:
        try:
            async with pg() as session, session.begin():
                return await svc.create_booking(
                    session, 1, check_in, check_out, "Family Loft", 4, TODAY
                )
        except svc.HotelError as exc:
            return exc

    results = await asyncio.gather(book(), book(), book())
    made = [r for r in results if isinstance(r, svc.BookingDetail)]
    assert len(made) == 2
    assert {m.room_number for m in made} == {"301", "302"}
    assert len({m.ref for m in made}) == 2


async def test_concurrent_moves_of_one_booking_never_double_book(
    pg: async_sessionmaker[AsyncSession],
) -> None:
    """Move 1 shifts booking X from Loft 301 to 302. Move 2, queued behind it, must see that.

    If move 2 loaded X before move 1 committed, it would think X is still in 301, find 301
    free on its dates, and keep X in 302 on top of booking Z.
    """
    day = TODAY + timedelta(days=200)
    d0 = (day, day + timedelta(days=1))
    d1 = (day + timedelta(days=10), day + timedelta(days=11))
    d2 = (day + timedelta(days=20), day + timedelta(days=21))
    # create_booking takes the first free Loft by room number (301, then 302).
    async with pg() as s, s.begin():
        x = await svc.create_booking(s, 1, *d0, "Family Loft", 1, TODAY)  # X: 301 on d0
        await svc.create_booking(s, 1, *d1, "Family Loft", 1, TODAY)  # Y: 301 on d1
        w = await svc.create_booking(s, 1, *d2, "Family Loft", 1, TODAY)  # W: 301 on d2
        z = await svc.create_booking(s, 1, *d2, "Family Loft", 1, TODAY)  # Z: 302 on d2
        await svc.cancel_own_booking(s, 1, w.booking_id)  # 301 is free again on d2
    assert (x.room_number, z.room_number) == ("301", "302")

    async with pg() as first, pg() as second:
        await first.begin()
        moved = await svc.modify_booking_dates(first, 1, x.booking_id, *d1, TODAY)
        assert moved.room_number == "302"  # 301 is taken by Y on d1
        task = asyncio.create_task(_move(second, x.booking_id, d2))
        await asyncio.sleep(0.5)  # let move 2 start and block on the room lock
        assert not task.done()
        await first.commit()
        result = await task
    assert result.room_number == "301"  # 302 holds Z on d2

    async with pg() as s:
        rows = (await s.execute(
            select(Booking.room_id, Booking.check_in, Booking.check_out)
            .where(Booking.status.in_(svc.ACTIVE_STATUSES))
        )).all()  # fmt: skip
    nights = [(room, c + timedelta(n)) for room, c, o in rows for n in range((o - c).days)]
    assert len(nights) == len(set(nights))


async def _move(
    session: AsyncSession, booking_id: int, dates: tuple[date, date]
) -> svc.BookingDetail:
    async with session.begin():
        return await svc.modify_booking_dates(session, 1, booking_id, *dates, TODAY)
