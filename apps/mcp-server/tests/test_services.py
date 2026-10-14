"""Tool business logic and data scoping, on SQLite with the seed loaded."""

from datetime import timedelta
from decimal import Decimal

import pytest
from hotel_mcp import services as svc
from hotel_mcp.models import Booking, Guest, Payment, StaffAccessGrant
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.conftest import TODAY

IN = TODAY + timedelta(days=100)
OUT = TODAY + timedelta(days=103)


async def _verify(session: AsyncSession, ref: str, last: str) -> svc.VerifyResult:
    result = await svc.verify_guest(session, ref, last)
    assert result.verified
    return result


# --- verify_guest ---


async def test_verify_guest_returns_guest_id_and_all_their_bookings(session: AsyncSession) -> None:
    result = await _verify(session, "LRK-1001", "Okafor")
    guest = await session.scalar(select(Guest).where(Guest.last_name == "Okafor"))
    assert guest is not None
    assert result.guest_id == guest.id
    assert result.first_name == "Amara"
    owned = set(await session.scalars(select(Booking.ref).where(Booking.guest_id == guest.id)))
    assert {b.ref for b in result.bookings} == owned
    assert "LRK-1001" in owned
    assert all(isinstance(b.booking_id, int) for b in result.bookings)


async def test_verify_guest_is_case_and_whitespace_insensitive(session: AsyncSession) -> None:
    result = await svc.verify_guest(session, " lrk-1001 ", "OKAFOR ")
    assert result.verified


@pytest.mark.parametrize(
    ("ref", "last"),
    [("LRK-1001", "Brandt"), ("LRK-9999", "Okafor"), ("", ""), ("LRK-1001", "Okafo")],
)
async def test_verify_guest_mismatch_returns_unverified_without_guest_id(
    session: AsyncSession, ref: str, last: str
) -> None:
    result = await svc.verify_guest(session, ref, last)
    assert result == svc.VerifyResult(verified=False)
    assert result.guest_id is None
    assert result.bookings == []


# --- scoping ---


async def _two_guests(session: AsyncSession) -> tuple[int, int, int]:
    """(guest A id, guest A booking id, guest B booking id)."""
    a = await _verify(session, "LRK-1001", "Okafor")
    b = await _verify(session, "LRK-1002", "Brandt")
    assert a.guest_id is not None
    return a.guest_id, a.bookings[0].booking_id, b.bookings[0].booking_id


async def test_get_booking_returns_own_booking(session: AsyncSession) -> None:
    guest_id, own, _ = await _two_guests(session)
    detail = await svc.get_booking(session, guest_id, own)
    assert detail.guest_id == guest_id
    assert detail.nights == (detail.check_out - detail.check_in).days


async def test_other_guest_and_missing_booking_give_identical_error(session: AsyncSession) -> None:
    guest_id, _, other = await _two_guests(session)
    with pytest.raises(svc.HotelError) as other_guest:
        await svc.get_booking(session, guest_id, other)
    with pytest.raises(svc.HotelError) as missing:
        await svc.get_booking(session, guest_id, 999_999)
    assert str(other_guest.value) == str(missing.value) == svc.BOOKING_NOT_FOUND


async def test_cross_guest_write_changes_nothing(session: AsyncSession) -> None:
    guest_id, _, other = await _two_guests(session)
    before = await session.scalar(select(func.count()).select_from(Payment))
    with pytest.raises(svc.HotelError):
        await svc.record_money(session, "refund", guest_id, other, 50, "x")
    with pytest.raises(svc.HotelError):
        await svc.cancel_own_booking(session, guest_id, other)
    assert await session.scalar(select(func.count()).select_from(Payment)) == before
    assert (await session.get(Booking, other)).status == "confirmed"  # type: ignore[union-attr]


# --- read tier ---


async def test_check_availability_counts_free_rooms(session: AsyncSession) -> None:
    result = await svc.check_availability(session, IN, OUT, 4, TODAY)
    assert result.nights == 3
    assert [o.room_type for o in result.options] == ["Family Loft"]  # only room type for 4+
    assert result.options[0].rooms_available <= 2


async def test_check_availability_rejects_bad_dates(session: AsyncSession) -> None:
    with pytest.raises(svc.HotelError, match="after check-in"):
        await svc.check_availability(session, OUT, IN, 1, TODAY)
    with pytest.raises(svc.HotelError, match="past"):
        await svc.check_availability(session, TODAY - timedelta(days=1), OUT, 1, TODAY)


# --- low-risk write tier ---


async def test_create_booking_prices_by_nights_and_blocks_double_booking(
    session: AsyncSession,
) -> None:
    guest_id, _, _ = await _two_guests(session)
    made = []
    # Two Family Lofts exist; a third booking of the same dates must fail.
    for _ in range(2):
        made.append(await svc.create_booking(session, guest_id, IN, OUT, "family loft", 4, TODAY))
    assert {m.room_number for m in made} == {"301", "302"}
    assert made[0].amount == 379 * 3
    assert made[0].status == "confirmed"
    assert made[0].ref != made[1].ref
    with pytest.raises(svc.HotelError, match="No family loft room is free"):
        await svc.create_booking(session, guest_id, IN, OUT, "family loft", 4, TODAY)


async def test_booking_refs_keep_counting_past_9999(session: AsyncSession) -> None:
    guest_id, own, _ = await _two_guests(session)
    booking = await session.get(Booking, own)
    assert booking is not None
    booking.ref = "LRK-9999"
    first = await svc.create_booking(session, guest_id, IN, OUT, "Deluxe King", 1, TODAY)
    second = await svc.create_booking(session, guest_id, IN, OUT, "Deluxe King", 1, TODAY)
    assert (first.ref, second.ref) == ("LRK-10000", "LRK-10001")


async def test_create_booking_unknown_room_type(session: AsyncSession) -> None:
    guest_id, _, _ = await _two_guests(session)
    with pytest.raises(svc.HotelError, match="Unknown room type"):
        await svc.create_booking(session, guest_id, IN, OUT, "Penthouse", 1, TODAY)


async def test_modify_booking_dates_recalculates_amount(session: AsyncSession) -> None:
    guest_id, own, _ = await _two_guests(session)
    before = await svc.get_booking(session, guest_id, own)
    after = await svc.modify_booking_dates(session, guest_id, own, IN, OUT, TODAY)
    assert (after.check_in, after.check_out) == (IN, OUT)
    assert after.room_type == before.room_type
    assert after.amount == pytest.approx(before.amount / before.nights * 3)


async def test_note_housekeeping_and_cancel(session: AsyncSession) -> None:
    guest_id, own, _ = await _two_guests(session)
    note = await svc.add_booking_note(session, guest_id, own, "  late arrival  ")
    assert note.text == "late arrival"
    hk = await svc.request_housekeeping(session, guest_id, own, "towels")
    assert hk.status == "open"
    cancelled = await svc.cancel_own_booking(session, guest_id, own)
    assert cancelled.status == "cancelled"
    assert "late arrival" in [n.text for n in cancelled.notes]
    with pytest.raises(svc.HotelError, match="Only confirmed"):
        await svc.cancel_own_booking(session, guest_id, own)


# --- money tier ---


@pytest.mark.parametrize("kind", ["refund", "comp_credit", "fee_waiver"])
async def test_money_tools_write_a_row(session: AsyncSession, kind: str) -> None:
    guest_id, own, _ = await _two_guests(session)
    out = await svc.record_money(session, kind, guest_id, own, 45.505, " goodwill ")
    row = await session.get(Payment, out.payment_id)
    assert row is not None
    assert (row.kind, row.amount, row.reason, row.booking_id) == (
        kind,
        Decimal("45.51"),
        "goodwill",
        own,
    )


async def test_money_has_no_server_side_cap(session: AsyncSession) -> None:
    # Limits are ArmorIQ policy (AGENTS.md rule 2); the server must not enforce one.
    guest_id, own, _ = await _two_guests(session)
    out = await svc.record_money(session, "refund", guest_id, own, 10_000, "big")
    assert out.amount == 10_000


@pytest.mark.parametrize("amount", [0, -5, 0.004])
async def test_money_rejects_non_positive_amounts(session: AsyncSession, amount: float) -> None:
    guest_id, own, _ = await _two_guests(session)
    with pytest.raises(svc.HotelError, match="greater than zero"):
        await svc.record_money(session, "refund", guest_id, own, amount, "x")


@pytest.mark.parametrize("amount", [float("inf"), float("nan")])
async def test_money_rejects_non_finite_amounts(session: AsyncSession, amount: float) -> None:
    guest_id, own, _ = await _two_guests(session)
    with pytest.raises(svc.HotelError, match="finite"):
        await svc.record_money(session, "refund", guest_id, own, amount, "x")


async def test_money_requires_reason(session: AsyncSession) -> None:
    guest_id, own, _ = await _two_guests(session)
    with pytest.raises(svc.HotelError, match="reason"):
        await svc.record_money(session, "refund", guest_id, own, 5, "   ")


# --- sensitive tier ---


async def test_export_guest_list_returns_everyone(session: AsyncSession) -> None:
    guests = await svc.export_guest_list(session)
    assert len(guests) == 30
    assert all(g.email.endswith("@example.com") for g in guests)


async def test_cancel_any_booking_ignores_ownership(session: AsyncSession) -> None:
    _, _, other = await _two_guests(session)
    result = await svc.cancel_any_booking(session, other, "staff request")
    assert result.status == "cancelled"


async def test_delete_guest_profile_cascades(session: AsyncSession) -> None:
    b = await _verify(session, "LRK-1002", "Brandt")
    assert b.guest_id is not None
    out = await svc.delete_guest_profile(session, b.guest_id)
    assert out.bookings_deleted == len(b.bookings)
    session.expunge_all()
    assert await session.get(Guest, b.guest_id) is None
    remaining = await session.scalar(
        select(func.count()).select_from(Booking).where(Booking.guest_id == b.guest_id)
    )
    assert remaining == 0


async def test_grant_staff_access_writes_row(session: AsyncSession) -> None:
    out = await svc.grant_staff_access(session, "eve@example.com", "manager")
    assert (await session.get(StaffAccessGrant, out.grant_id)) is not None
