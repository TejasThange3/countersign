"""Business logic for the hotel tools.

Each function takes an open `AsyncSession`; the caller owns the transaction. This module scopes
data to the guest it is given and validates business inputs (dates, positive amounts). It never
decides whether a caller is *allowed* to do something: that is ArmorIQ's job (AGENTS.md rule 2),
so there are no permission checks or money limits here.
"""

from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from pydantic import BaseModel
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from hotel_mcp.models import (
    Booking,
    BookingNote,
    Guest,
    HousekeepingRequest,
    Payment,
    Room,
    StaffAccessGrant,
)

# One message for "no such booking" and "booking belongs to someone else", so a caller can't
# use the difference to discover which booking ids exist.
BOOKING_NOT_FOUND = "Booking not found for this guest."
ACTIVE_STATUSES = ("confirmed", "checked_in")


class HotelError(Exception):
    """A business-rule failure whose message is safe to show to the caller."""


# --- Result models (these become the tools' structured output) ---


class BookingRef(BaseModel):
    booking_id: int
    ref: str
    check_in: date
    check_out: date
    status: str


class VerifyResult(BaseModel):
    """`guest_id` is what the agent bridge reads to switch identity; keep the name stable."""

    verified: bool
    guest_id: int | None = None
    first_name: str | None = None
    bookings: list[BookingRef] = []


class NoteOut(BaseModel):
    author: str
    text: str


class PaymentOut(BaseModel):
    payment_id: int
    booking_id: int
    kind: str
    amount: float
    reason: str


class BookingDetail(BaseModel):
    booking_id: int
    ref: str
    guest_id: int
    guest_name: str
    room_number: str
    room_type: str
    check_in: date
    check_out: date
    nights: int
    num_guests: int
    status: str
    amount: float
    notes: list[NoteOut]
    payments: list[PaymentOut]


class RoomTypeAvailability(BaseModel):
    room_type: str
    nightly_rate: float
    max_guests: int
    rooms_available: int


class Availability(BaseModel):
    check_in: date
    check_out: date
    nights: int
    options: list[RoomTypeAvailability]


class NoteAdded(BaseModel):
    booking_id: int
    note_id: int
    text: str


class HousekeepingOut(BaseModel):
    request_id: int
    booking_id: int
    request: str
    status: str


class GuestRecord(BaseModel):
    guest_id: int
    first_name: str
    last_name: str
    email: str
    phone: str
    loyalty_tier: str


class GuestDeleted(BaseModel):
    guest_id: int
    bookings_deleted: int


class StaffGrantOut(BaseModel):
    grant_id: int
    email: str
    role: str


# --- Static hotel facts ---

HOTEL_INFO: dict[str, object] = {
    "name": "The Larkspur",
    "description": "A 12-room boutique hotel in a restored 1920s townhouse.",
    "address": "14 Wren Lane, Harbor District (fictional)",
    "phone": "+1-555-0100",
    "check_in_time": "15:00",
    "check_out_time": "11:00",
    "breakfast": "Included, 07:00-10:30 in the garden room.",
    "amenities": ["free wifi", "rooftop terrace", "bike rental", "luggage storage"],
    "parking": "No on-site parking; public garage two blocks away.",
    "pets": "Dogs under 15 kg allowed in Garden rooms, 25 dollars per night.",
}

CANCELLATION_POLICY = (
    "Free cancellation up to 48 hours before check-in. Cancellations within 48 hours are "
    "charged one night. No-shows are charged the full stay. Refunds for disputes, service "
    "problems or goodwill credits are handled by the front desk and may need manager approval."
)


# --- Helpers ---


def to_money(amount: float | Decimal) -> Decimal:
    if not Decimal(str(amount)).is_finite():
        raise HotelError("Amount must be a finite number.")
    value = Decimal(str(amount)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if value <= 0:
        raise HotelError("Amount must be greater than zero.")
    return value


def _check_dates(check_in: date, check_out: date, today: date) -> int:
    if check_out <= check_in:
        raise HotelError("Check-out must be after check-in.")
    if check_in < today:
        raise HotelError("Check-in cannot be in the past.")
    return (check_out - check_in).days


async def _guest_booking(session: AsyncSession, guest_id: int, booking_id: int) -> Booking:
    """Load a booking only if it belongs to `guest_id`. The core of data scoping."""
    booking = await session.scalar(
        select(Booking)
        .where(Booking.id == booking_id, Booking.guest_id == guest_id)
        .options(
            selectinload(Booking.room),
            selectinload(Booking.guest),
            selectinload(Booking.notes),
            selectinload(Booking.payments),
        )
        # Refresh rows already in the session so details reflect changes made in this call.
        .execution_options(populate_existing=True)
    )
    if booking is None:
        raise HotelError(BOOKING_NOT_FOUND)
    return booking


async def _require_guest(session: AsyncSession, guest_id: int) -> Guest:
    guest = await session.get(Guest, guest_id)
    if guest is None:
        raise HotelError("Guest not found.")
    return guest


async def _lock_rooms(session: AsyncSession) -> None:
    """Serialise every call that assigns rooms, for the rest of the transaction.

    Locks all room rows (Postgres `FOR UPDATE`; a no-op on SQLite), so a concurrent create or
    move waits, then sees the other one's committed booking. Callers must take the lock *before*
    loading any booking they will change, or they would work from stale state. With 12 rooms
    this costs nothing, and it also keeps generated booking refs unique.
    """
    await session.execute(select(Room.id).order_by(Room.id).with_for_update())


async def _free_room_ids(
    session: AsyncSession, check_in: date, check_out: date, exclude_booking_id: int | None = None
) -> set[int]:
    """Rooms with no active booking overlapping [check_in, check_out)."""
    overlap = and_(
        Booking.status.in_(ACTIVE_STATUSES),
        Booking.check_in < check_out,
        Booking.check_out > check_in,
    )
    if exclude_booking_id is not None:
        overlap = and_(overlap, Booking.id != exclude_booking_id)
    busy = set(await session.scalars(select(Booking.room_id).where(overlap)))
    all_rooms = set(await session.scalars(select(Room.id)))
    return all_rooms - busy


def _detail(booking: Booking) -> BookingDetail:
    return BookingDetail(
        booking_id=booking.id,
        ref=booking.ref,
        guest_id=booking.guest_id,
        guest_name=f"{booking.guest.first_name} {booking.guest.last_name}",
        room_number=booking.room.number,
        room_type=booking.room.room_type,
        check_in=booking.check_in,
        check_out=booking.check_out,
        nights=(booking.check_out - booking.check_in).days,
        num_guests=booking.num_guests,
        status=booking.status,
        amount=float(booking.amount),
        notes=[NoteOut(author=n.author, text=n.text) for n in booking.notes],
        payments=[_payment_out(p) for p in booking.payments],
    )


def _payment_out(payment: Payment) -> PaymentOut:
    return PaymentOut(
        payment_id=payment.id,
        booking_id=payment.booking_id,
        kind=payment.kind,
        amount=float(payment.amount),
        reason=payment.reason,
    )


async def _reload(session: AsyncSession, booking: Booking) -> BookingDetail:
    """Flush changes and return fresh details (relationships included)."""
    await session.flush()
    return _detail(await _guest_booking(session, booking.guest_id, booking.id))


# --- Read tier ---


async def verify_guest(session: AsyncSession, booking_ref: str, last_name: str) -> VerifyResult:
    match = await session.execute(
        select(Guest.id, Guest.first_name)
        .join(Booking, Booking.guest_id == Guest.id)
        .where(
            func.upper(Booking.ref) == booking_ref.strip().upper(),
            func.lower(Guest.last_name) == last_name.strip().lower(),
        )
    )
    row = match.first()
    if row is None:
        return VerifyResult(verified=False)
    guest_id, first_name = row
    bookings = await session.scalars(
        select(Booking).where(Booking.guest_id == guest_id).order_by(Booking.check_in)
    )
    return VerifyResult(
        verified=True,
        guest_id=guest_id,
        first_name=first_name,
        bookings=[
            BookingRef(
                booking_id=b.id,
                ref=b.ref,
                check_in=b.check_in,
                check_out=b.check_out,
                status=b.status,
            )
            for b in bookings
        ],
    )


async def get_booking(session: AsyncSession, guest_id: int, booking_id: int) -> BookingDetail:
    return _detail(await _guest_booking(session, guest_id, booking_id))


async def check_availability(
    session: AsyncSession,
    check_in: date,
    check_out: date,
    num_guests: int,
    today: date,
) -> Availability:
    nights = _check_dates(check_in, check_out, today)
    free = await _free_room_ids(session, check_in, check_out)
    rooms = (await session.scalars(select(Room).where(Room.max_guests >= num_guests))).all()
    by_type: dict[str, RoomTypeAvailability] = {}
    for room in rooms:
        option = by_type.setdefault(
            room.room_type,
            RoomTypeAvailability(
                room_type=room.room_type,
                nightly_rate=float(room.nightly_rate),
                max_guests=room.max_guests,
                rooms_available=0,
            ),
        )
        if room.id in free:
            option.rooms_available += 1
    options = sorted(
        (o for o in by_type.values() if o.rooms_available), key=lambda o: o.nightly_rate
    )
    return Availability(check_in=check_in, check_out=check_out, nights=nights, options=options)


# --- Low-risk write tier ---


async def create_booking(
    session: AsyncSession,
    guest_id: int,
    check_in: date,
    check_out: date,
    room_type: str,
    num_guests: int,
    today: date,
) -> BookingDetail:
    await _require_guest(session, guest_id)
    nights = _check_dates(check_in, check_out, today)
    await _lock_rooms(session)
    free = await _free_room_ids(session, check_in, check_out)
    rooms = (
        await session.scalars(
            select(Room)
            .where(func.lower(Room.room_type) == room_type.strip().lower())
            .order_by(Room.number)
        )
    ).all()
    if not rooms:
        raise HotelError(f"Unknown room type {room_type!r}.")
    room = next((r for r in rooms if r.id in free and r.max_guests >= num_guests), None)
    if room is None:
        raise HotelError(f"No {room_type} room is free for those dates and party size.")
    booking = Booking(
        ref=await _next_ref(session),
        guest_id=guest_id,
        room_id=room.id,
        check_in=check_in,
        check_out=check_out,
        num_guests=num_guests,
        status="confirmed",
        amount=room.nightly_rate * nights,
    )
    session.add(booking)
    await session.flush()
    return _detail(await _guest_booking(session, guest_id, booking.id))


async def _next_ref(session: AsyncSession) -> str:
    # Refs are LRK-<digits>; ordering by length first makes LRK-10000 sort after LRK-9999.
    highest = await session.scalar(
        select(Booking.ref).order_by(func.length(Booking.ref).desc(), Booking.ref.desc()).limit(1)
    )
    return f"LRK-{int(highest.removeprefix('LRK-')) + 1 if highest else 1001}"


async def modify_booking_dates(
    session: AsyncSession,
    guest_id: int,
    booking_id: int,
    check_in: date,
    check_out: date,
    today: date,
) -> BookingDetail:
    # Lock before loading: a concurrent move of this booking must be visible to us.
    await _lock_rooms(session)
    booking = await _guest_booking(session, guest_id, booking_id)
    if booking.status != "confirmed":
        raise HotelError(f"Only confirmed bookings can be changed (this one is {booking.status}).")
    nights = _check_dates(check_in, check_out, today)
    free = await _free_room_ids(session, check_in, check_out, exclude_booking_id=booking.id)
    room = booking.room
    if room.id not in free:
        same_type = (
            await session.scalars(
                select(Room).where(Room.room_type == room.room_type).order_by(Room.number)
            )
        ).all()
        alternative = next(
            (r for r in same_type if r.id in free and r.max_guests >= booking.num_guests), None
        )
        if alternative is None:
            raise HotelError(f"No {room.room_type} room is free for the new dates.")
        room = alternative
    booking.room_id = room.id
    booking.check_in = check_in
    booking.check_out = check_out
    booking.amount = room.nightly_rate * nights
    return await _reload(session, booking)


async def add_booking_note(
    session: AsyncSession, guest_id: int, booking_id: int, note: str
) -> NoteAdded:
    booking = await _guest_booking(session, guest_id, booking_id)
    text = note.strip()
    if not text:
        raise HotelError("Note cannot be empty.")
    row = BookingNote(booking_id=booking.id, author="guest", text=text)
    session.add(row)
    await session.flush()
    return NoteAdded(booking_id=booking.id, note_id=row.id, text=row.text)


async def request_housekeeping(
    session: AsyncSession, guest_id: int, booking_id: int, request: str
) -> HousekeepingOut:
    booking = await _guest_booking(session, guest_id, booking_id)
    text = request.strip()
    if not text:
        raise HotelError("Request cannot be empty.")
    row = HousekeepingRequest(booking_id=booking.id, request=text, status="open")
    session.add(row)
    await session.flush()
    return HousekeepingOut(
        request_id=row.id, booking_id=booking.id, request=row.request, status=row.status
    )


async def cancel_own_booking(
    session: AsyncSession, guest_id: int, booking_id: int
) -> BookingDetail:
    booking = await _guest_booking(session, guest_id, booking_id)
    return await _cancel(session, booking)


async def _cancel(session: AsyncSession, booking: Booking) -> BookingDetail:
    if booking.status != "confirmed":
        raise HotelError(
            f"Only confirmed bookings can be cancelled (this one is {booking.status})."
        )
    booking.status = "cancelled"
    return await _reload(session, booking)


# --- Money tier ---


async def record_money(
    session: AsyncSession,
    kind: str,
    guest_id: int,
    booking_id: int,
    amount: float,
    reason: str,
) -> PaymentOut:
    """Write a refund, comp credit or fee waiver row. No cap: limits are ArmorIQ policy."""
    booking = await _guest_booking(session, guest_id, booking_id)
    value = to_money(amount)
    if not reason.strip():
        raise HotelError("A reason is required.")
    row = Payment(booking_id=booking.id, kind=kind, amount=value, reason=reason.strip())
    session.add(row)
    await session.flush()
    return _payment_out(row)


# --- Sensitive / destructive tier ---


async def export_guest_list(session: AsyncSession) -> list[GuestRecord]:
    guests = (await session.scalars(select(Guest).order_by(Guest.id))).all()
    return [
        GuestRecord(
            guest_id=g.id,
            first_name=g.first_name,
            last_name=g.last_name,
            email=g.email,
            phone=g.phone,
            loyalty_tier=g.loyalty_tier,
        )
        for g in guests
    ]


async def cancel_any_booking(session: AsyncSession, booking_id: int, reason: str) -> BookingDetail:
    booking = await session.get(Booking, booking_id)
    if booking is None:
        raise HotelError(BOOKING_NOT_FOUND)
    # If the cancel fails, the tool's transaction rolls this note back too.
    session.add(
        BookingNote(booking_id=booking.id, author="front_desk", text=f"Cancelled: {reason}")
    )
    return await _cancel(session, booking)


async def delete_guest_profile(session: AsyncSession, target_guest_id: int) -> GuestDeleted:
    guest = await _require_guest(session, target_guest_id)
    count = await session.scalar(
        select(func.count()).select_from(Booking).where(Booking.guest_id == guest.id)
    )
    await session.delete(guest)
    await session.flush()
    return GuestDeleted(guest_id=target_guest_id, bookings_deleted=count or 0)


async def grant_staff_access(session: AsyncSession, email: str, role: str) -> StaffGrantOut:
    if not email.strip() or not role.strip():
        raise HotelError("Email and role are required.")
    row = StaffAccessGrant(email=email.strip(), role=role.strip())
    session.add(row)
    await session.flush()
    return StaffGrantOut(grant_id=row.id, email=row.email, role=row.role)
