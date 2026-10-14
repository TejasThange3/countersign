"""Seed data shape, determinism and reset (SQLite)."""

from datetime import timedelta

import pytest
from hotel_mcp.models import (
    Booking,
    BookingNote,
    Guest,
    HousekeepingRequest,
    Payment,
    Room,
    StaffAccessGrant,
)
from hotel_mcp.seed import INJECTION_BOOKING_REF, INJECTION_NOTE, reset, seed
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tests.conftest import TODAY


async def _count(session: AsyncSession, model: type) -> int:
    return await session.scalar(select(func.count()).select_from(model)) or 0


async def snapshot(session: AsyncSession) -> list[tuple]:
    """Bookings, payments, notes and grants by natural keys (not ids), to compare states."""
    queries = [
        select(
            Booking.ref, Guest.email, Room.number, Booking.check_in, Booking.check_out,
            Booking.status, Booking.amount,
        ).join(Guest).join(Room).order_by(Booking.ref),
        select(Booking.ref, Payment.kind, Payment.amount, Payment.reason)
        .join(Booking).order_by(Booking.ref, Payment.kind, Payment.amount),
        select(Booking.ref, BookingNote.text).join(Booking).order_by(Booking.ref, BookingNote.text),
        select(Guest.email).order_by(Guest.email),
        select(StaffAccessGrant.email),
        select(HousekeepingRequest.request),
    ]  # fmt: skip
    rows: list[tuple] = []
    for query in queries:
        rows += [tuple(r) for r in (await session.execute(query)).all()]
    return rows


async def test_seed_counts(session: AsyncSession) -> None:
    assert await _count(session, Guest) == 30
    assert await _count(session, Booking) == 50
    assert await _count(session, Room) == 12
    assert 3 <= await _count(session, Payment)


async def test_seed_has_planted_injection_note(session: AsyncSession) -> None:
    text = await session.scalar(
        select(BookingNote.text).join(Booking).where(Booking.ref == INJECTION_BOOKING_REF)
    )
    assert text == INJECTION_NOTE


async def test_seed_never_double_books_a_room(session: AsyncSession) -> None:
    rows = (await session.scalars(select(Booking))).all()
    nights: set[tuple[int, object]] = set()
    for b in rows:
        for d in range((b.check_out - b.check_in).days):
            night = (b.room_id, b.check_in + timedelta(days=d))
            assert night not in nights, b.ref
            nights.add(night)


async def test_demo_bookings_are_future_and_confirmed(session: AsyncSession) -> None:
    for ref in ("LRK-1001", "LRK-1002", "LRK-1003"):
        b = await session.scalar(select(Booking).where(Booking.ref == ref))
        assert b is not None
        assert b.status == "confirmed"
        assert b.check_in > TODAY


async def test_seed_refuses_non_empty_database(session: AsyncSession) -> None:
    with pytest.raises(RuntimeError, match="reset"):
        await seed(session, TODAY)


async def test_reset_restores_seed_state(sessionmaker: async_sessionmaker[AsyncSession]) -> None:
    async with sessionmaker() as s:
        original = await snapshot(s)
    async with sessionmaker() as s, s.begin():
        booking = await s.scalar(select(Booking).where(Booking.ref == "LRK-1001"))
        assert booking is not None
        booking.status = "cancelled"
        s.add(Payment(booking_id=booking.id, kind="refund", amount=999, reason="attack"))
        s.add(StaffAccessGrant(email="eve@example.com", role="manager"))
    async with sessionmaker() as s:
        assert await snapshot(s) != original
    async with sessionmaker() as s, s.begin():
        await reset(s, TODAY)
    async with sessionmaker() as s:
        assert await snapshot(s) == original
