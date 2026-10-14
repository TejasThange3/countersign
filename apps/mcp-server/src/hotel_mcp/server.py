"""The `hotel-mcp` FastMCP server: front-desk tools grouped by risk tier.

Docstrings and argument descriptions here are what the model reads, so they say what each tool
does and when to use it. Identity arguments (`guest_id`) are injected by the agent's ArmorIQ
bridge and hidden from the model; tools trust them to scope data and nothing else. Whether a call
may run at all is decided by ArmorIQ before it reaches this server (AGENTS.md rules 1-3).
"""

import hmac
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from datetime import date
from typing import Annotated

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from pydantic import Field
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from starlette.requests import Request
from starlette.responses import JSONResponse, PlainTextResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from hotel_mcp import services as svc

GuestId = Annotated[
    int, Field(description="Verified guest id. Supplied by the system; do not guess it.")
]
BookingId = Annotated[int, Field(description="Booking id from verify_guest or get_booking.")]
Amount = Annotated[float, Field(gt=0, description="Amount in dollars, e.g. 45.50.")]
Reason = Annotated[str, Field(min_length=1, description="Why this is being done, in a sentence.")]
CheckIn = Annotated[date, Field(description="Check-in date, YYYY-MM-DD.")]
CheckOut = Annotated[date, Field(description="Check-out date, YYYY-MM-DD (after check-in).")]
NumGuests = Annotated[int, Field(ge=1, le=6, description="Number of people staying.")]

READ = {"readOnlyHint": True, "destructiveHint": False}
WRITE = {"readOnlyHint": False, "destructiveHint": False}
DESTRUCTIVE = {"readOnlyHint": False, "destructiveHint": True}


def build_server(
    sessionmaker: async_sessionmaker[AsyncSession],
    today: Callable[[], date] = date.today,
) -> FastMCP:
    """Create the server. `sessionmaker` and `today` are parameters so tests can swap them."""
    mcp = FastMCP(
        name="hotel-mcp",
        instructions=(
            "Front-desk tools for The Larkspur, a boutique hotel. Verify the caller with "
            "verify_guest before using any tool that needs a guest_id."
        ),
        mask_error_details=True,
    )

    @asynccontextmanager
    async def tx() -> AsyncIterator[AsyncSession]:
        """One transaction per tool call; business errors become ToolErrors the model sees."""
        try:
            async with sessionmaker() as session, session.begin():
                yield session
        except svc.HotelError as exc:
            raise ToolError(str(exc)) from exc

    # --- Read tier ---

    @mcp.tool(tags={"read"}, annotations=READ)
    async def verify_guest(
        booking_ref: Annotated[str, Field(description="Booking reference, e.g. LRK-1001.")],
        last_name: Annotated[str, Field(description="Guest's last name as on the booking.")],
    ) -> svc.VerifyResult:
        """Verify a caller's identity with their booking reference and last name.

        Call this before anything that needs a guest_id. Returns verified=false if the
        reference and name do not match; otherwise the guest's id and all their bookings.
        """
        async with tx() as s:
            return await svc.verify_guest(s, booking_ref, last_name)

    @mcp.tool(tags={"read"}, annotations=READ)
    async def get_booking(guest_id: GuestId, booking_id: BookingId) -> svc.BookingDetail:
        """Get full details of one of the verified guest's bookings: room, dates, status,
        price, notes and payments."""
        async with tx() as s:
            return await svc.get_booking(s, guest_id, booking_id)

    @mcp.tool(tags={"read"}, annotations=READ)
    async def check_availability(
        check_in: CheckIn, check_out: CheckOut, num_guests: NumGuests = 1
    ) -> svc.Availability:
        """List room types free for the given dates and party size, with nightly rates."""
        async with tx() as s:
            return await svc.check_availability(s, check_in, check_out, num_guests, today())

    @mcp.tool(tags={"read"}, annotations=READ)
    async def get_hotel_info() -> dict[str, object]:
        """General hotel facts: address, check-in/out times, breakfast, amenities, parking, pets."""
        return svc.HOTEL_INFO

    @mcp.tool(tags={"read"}, annotations=READ)
    async def get_cancellation_policy() -> str:
        """The hotel's cancellation and refund policy, to read to the guest."""
        return svc.CANCELLATION_POLICY

    # --- Low-risk write tier ---

    @mcp.tool(tags={"write"}, annotations=WRITE)
    async def create_booking(
        guest_id: GuestId,
        check_in: CheckIn,
        check_out: CheckOut,
        room_type: Annotated[
            str, Field(description="Room type from check_availability, e.g. Classic Queen.")
        ],
        num_guests: NumGuests = 1,
    ) -> svc.BookingDetail:
        """Book a new stay for the verified guest. Check availability first."""
        async with tx() as s:
            return await svc.create_booking(
                s, guest_id, check_in, check_out, room_type, num_guests, today()
            )

    @mcp.tool(tags={"write"}, annotations=WRITE)
    async def modify_booking_dates(
        guest_id: GuestId, booking_id: BookingId, check_in: CheckIn, check_out: CheckOut
    ) -> svc.BookingDetail:
        """Move one of the verified guest's confirmed bookings to new dates. The price is
        recalculated for the new number of nights."""
        async with tx() as s:
            return await svc.modify_booking_dates(
                s, guest_id, booking_id, check_in, check_out, today()
            )

    @mcp.tool(tags={"write"}, annotations=WRITE)
    async def add_booking_note(
        guest_id: GuestId,
        booking_id: BookingId,
        note: Annotated[str, Field(min_length=1, description="The note, e.g. 'late arrival'.")],
    ) -> svc.NoteAdded:
        """Add a note to one of the verified guest's bookings (arrival time, preferences)."""
        async with tx() as s:
            return await svc.add_booking_note(s, guest_id, booking_id, note)

    @mcp.tool(tags={"write"}, annotations=WRITE)
    async def request_housekeeping(
        guest_id: GuestId,
        booking_id: BookingId,
        request: Annotated[str, Field(min_length=1, description="What is needed, e.g. towels.")],
    ) -> svc.HousekeepingOut:
        """Send a housekeeping request for the verified guest's room."""
        async with tx() as s:
            return await svc.request_housekeeping(s, guest_id, booking_id, request)

    @mcp.tool(tags={"write"}, annotations=WRITE)
    async def cancel_own_booking(guest_id: GuestId, booking_id: BookingId) -> svc.BookingDetail:
        """Cancel one of the verified guest's own confirmed bookings. Read them the
        cancellation policy first."""
        async with tx() as s:
            return await svc.cancel_own_booking(s, guest_id, booking_id)

    # --- Money tier (every tool takes `amount`, so ArmorIQ thresholds apply) ---

    @mcp.tool(tags={"money"}, annotations=WRITE)
    async def issue_refund(
        guest_id: GuestId, booking_id: BookingId, amount: Amount, reason: Reason
    ) -> svc.PaymentOut:
        """Refund money to the verified guest for one of their bookings."""
        async with tx() as s:
            return await svc.record_money(s, "refund", guest_id, booking_id, amount, reason)

    @mcp.tool(tags={"money"}, annotations=WRITE)
    async def apply_comp_credit(
        guest_id: GuestId, booking_id: BookingId, amount: Amount, reason: Reason
    ) -> svc.PaymentOut:
        """Give the verified guest a goodwill credit on one of their bookings."""
        async with tx() as s:
            return await svc.record_money(s, "comp_credit", guest_id, booking_id, amount, reason)

    @mcp.tool(tags={"money"}, annotations=WRITE)
    async def waive_fee(
        guest_id: GuestId, booking_id: BookingId, amount: Amount, reason: Reason
    ) -> svc.PaymentOut:
        """Waive a fee (late checkout, cancellation, pet fee) on one of the verified guest's
        bookings."""
        async with tx() as s:
            return await svc.record_money(s, "fee_waiver", guest_id, booking_id, amount, reason)

    # --- Sensitive / destructive tier (staff-only operations) ---

    @mcp.tool(tags={"sensitive"}, annotations=READ)
    async def export_guest_list() -> list[svc.GuestRecord]:
        """Staff only: export every guest's name, email, phone and loyalty tier."""
        async with tx() as s:
            return await svc.export_guest_list(s)

    @mcp.tool(tags={"sensitive"}, annotations=DESTRUCTIVE)
    async def cancel_any_booking(
        booking_id: Annotated[int, Field(description="Any booking id, for any guest.")],
        reason: Reason,
    ) -> svc.BookingDetail:
        """Staff only: cancel any guest's booking."""
        async with tx() as s:
            return await svc.cancel_any_booking(s, booking_id, reason)

    @mcp.tool(tags={"sensitive"}, annotations=DESTRUCTIVE)
    async def delete_guest_profile(
        target_guest_id: Annotated[int, Field(description="Id of the guest to delete.")],
    ) -> svc.GuestDeleted:
        """Staff only: permanently delete a guest profile and all of its bookings."""
        async with tx() as s:
            return await svc.delete_guest_profile(s, target_guest_id)

    @mcp.tool(tags={"sensitive"}, annotations=DESTRUCTIVE)
    async def grant_staff_access(
        email: Annotated[str, Field(description="Email of the person to grant access to.")],
        role: Annotated[str, Field(description="Staff role, e.g. front_desk or manager.")],
    ) -> svc.StaffGrantOut:
        """Staff only: give someone staff access to hotel systems."""
        async with tx() as s:
            return await svc.grant_staff_access(s, email, role)

    @mcp.custom_route("/health", methods=["GET"])
    async def health(_: Request) -> PlainTextResponse:
        return PlainTextResponse("ok")

    return mcp


class BearerAuthMiddleware:
    """Reject HTTP requests without `Authorization: Bearer <token>`.

    Without this, anyone who learns the public URL could call tools directly and skip ArmorIQ.
    `/health` stays open so hosts can probe liveness without the secret.
    """

    def __init__(self, app: ASGIApp, token: str, open_paths: frozenset[str]) -> None:
        if not token:
            raise ValueError("MCP_BEARER_TOKEN is empty; refusing to start an open server.")
        self.app = app
        self.expected = f"Bearer {token}".encode()
        self.open_paths = open_paths

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        # Fail closed: only lifespan events and the open paths skip the token check.
        if scope["type"] == "lifespan" or scope.get("path") in self.open_paths:
            await self.app(scope, receive, send)
            return
        if scope["type"] != "http":
            await send({"type": "websocket.close", "code": 1008})
            return
        supplied = dict(scope["headers"]).get(b"authorization", b"")
        if not hmac.compare_digest(supplied, self.expected):
            response = JSONResponse(
                {"error": "unauthorized"},
                status_code=401,
                headers={"WWW-Authenticate": "Bearer"},
            )
            await response(scope, receive, send)
            return
        await self.app(scope, receive, send)


def create_app(
    token: str,
    sessionmaker: async_sessionmaker[AsyncSession],
    today: Callable[[], date] = date.today,
) -> ASGIApp:
    """The deployable ASGI app: streamable HTTP at /mcp behind bearer auth."""
    app = build_server(sessionmaker, today).http_app(path="/mcp")
    return BearerAuthMiddleware(app, token, open_paths=frozenset({"/health"}))
