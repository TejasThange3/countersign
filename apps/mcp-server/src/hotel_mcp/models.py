"""SQLAlchemy models for the hotel.

Column types are kept portable (no Postgres-only types) so unit tests can run on SQLite while
production and integration tests run on Postgres.
"""

from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import Date, DateTime, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

Money = Numeric(10, 2)


def _now() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class Guest(Base):
    __tablename__ = "guests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    first_name: Mapped[str] = mapped_column(String(80))
    last_name: Mapped[str] = mapped_column(String(80))
    email: Mapped[str] = mapped_column(String(200), unique=True)
    phone: Mapped[str] = mapped_column(String(40))
    loyalty_tier: Mapped[str] = mapped_column(String(20), default="standard")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    bookings: Mapped[list["Booking"]] = relationship(
        back_populates="guest", cascade="all, delete-orphan", passive_deletes=True
    )


class Room(Base):
    __tablename__ = "rooms"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    number: Mapped[str] = mapped_column(String(10), unique=True)
    room_type: Mapped[str] = mapped_column(String(40))
    nightly_rate: Mapped[Decimal] = mapped_column(Money)
    max_guests: Mapped[int] = mapped_column(Integer)


class Booking(Base):
    __tablename__ = "bookings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ref: Mapped[str] = mapped_column(String(20), unique=True)
    guest_id: Mapped[int] = mapped_column(ForeignKey("guests.id", ondelete="CASCADE"), index=True)
    room_id: Mapped[int] = mapped_column(ForeignKey("rooms.id"))
    check_in: Mapped[date] = mapped_column(Date)
    check_out: Mapped[date] = mapped_column(Date)
    num_guests: Mapped[int] = mapped_column(Integer, default=1)
    # confirmed | cancelled | checked_in | checked_out
    status: Mapped[str] = mapped_column(String(20), default="confirmed")
    amount: Mapped[Decimal] = mapped_column(Money)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    guest: Mapped[Guest] = relationship(back_populates="bookings")
    room: Mapped[Room] = relationship()
    notes: Mapped[list["BookingNote"]] = relationship(
        cascade="all, delete-orphan", passive_deletes=True, order_by="BookingNote.id"
    )
    payments: Mapped[list["Payment"]] = relationship(
        cascade="all, delete-orphan", passive_deletes=True, order_by="Payment.id"
    )


class BookingNote(Base):
    __tablename__ = "booking_notes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    booking_id: Mapped[int] = mapped_column(
        ForeignKey("bookings.id", ondelete="CASCADE"), index=True
    )
    author: Mapped[str] = mapped_column(String(40))  # "guest" | "front_desk" | "system"
    text: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Payment(Base):
    """Money movement on a booking. Refunds and credits are rows here; no provider is called."""

    __tablename__ = "payments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    booking_id: Mapped[int] = mapped_column(
        ForeignKey("bookings.id", ondelete="CASCADE"), index=True
    )
    # charge | refund | comp_credit | fee_waiver
    kind: Mapped[str] = mapped_column(String(20))
    amount: Mapped[Decimal] = mapped_column(Money)
    reason: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class HousekeepingRequest(Base):
    __tablename__ = "housekeeping_requests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    booking_id: Mapped[int] = mapped_column(
        ForeignKey("bookings.id", ondelete="CASCADE"), index=True
    )
    request: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="open")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class StaffAccessGrant(Base):
    __tablename__ = "staff_access_grants"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(200))
    role: Mapped[str] = mapped_column(String(40))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


ALL_TABLES = [
    "staff_access_grants",
    "housekeeping_requests",
    "payments",
    "booking_notes",
    "bookings",
    "rooms",
    "guests",
]
