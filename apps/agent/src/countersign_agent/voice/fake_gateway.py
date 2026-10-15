"""FAKE gateway for development and unit tests only. It never calls ArmorIQ or hotel-mcp.

It copies hotel-mcp's tool signatures (with guest_id stripped, as the real bridge does) and
makes scripted decisions so the voice pipeline can be built before the bridge lane merges:

- sensitive tools are blocked,
- money tools above $100 are held for approval, smaller amounts are allowed,
- everything else is allowed and returns canned data.

Every result says `armoriq_mode="disabled"`: nothing here is an ArmorIQ decision, and nothing
produced with it may be reported as one (AGENTS.md rule 5). `app.py` logs a loud warning
whenever this factory is in use.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, Literal

from countersign_agent.contracts import (
    Decision,
    EventSink,
    GatewayEvent,
    Outcome,
    ToolResult,
    ToolSpec,
)

FAKE_HOLD_LIMIT = 100.0

_DATE = {"type": "string", "format": "date"}
_BOOKING_ID = {"type": "integer", "description": "Booking id from verify_guest or get_booking."}
_AMOUNT = {"type": "number", "description": "Amount in dollars, e.g. 45.50."}
_REASON = {"type": "string", "description": "Why this is being done, in a sentence."}
_NUM_GUESTS = {"type": "integer", "description": "Number of people staying."}


def _obj(properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {"type": "object", "properties": properties, "required": required}


def _money(name: str, description: str) -> ToolSpec:
    return ToolSpec(
        name=name,
        description=description,
        parameters=_obj(
            {"booking_id": _BOOKING_ID, "amount": _AMOUNT, "reason": _REASON},
            ["booking_id", "amount", "reason"],
        ),
        tier="money",
    )


FAKE_TOOL_SPECS: list[ToolSpec] = [
    ToolSpec(
        name="verify_guest",
        description="Verify a caller's identity with their booking reference and last name.",
        parameters=_obj(
            {
                "booking_ref": {"type": "string", "description": "Booking reference, LRK-1001."},
                "last_name": {"type": "string", "description": "Guest's last name."},
            },
            ["booking_ref", "last_name"],
        ),
        tier="read",
    ),
    ToolSpec(
        name="check_availability",
        description="List room types free for the given dates and party size, with rates.",
        parameters=_obj(
            {"check_in": _DATE, "check_out": _DATE, "num_guests": _NUM_GUESTS},
            ["check_in", "check_out"],
        ),
        tier="read",
    ),
    ToolSpec(
        name="get_booking",
        description="Get full details of one of the verified guest's bookings.",
        parameters=_obj({"booking_id": _BOOKING_ID}, ["booking_id"]),
        tier="read",
    ),
    _money("issue_refund", "Refund money to the verified guest for one of their bookings."),
    _money("apply_comp_credit", "Give the verified guest a goodwill credit on a booking."),
    ToolSpec(
        name="export_guest_list",
        description="Staff only: export every guest's name, email, phone and loyalty tier.",
        parameters=_obj({}, []),
        tier="sensitive",
    ),
]

_CANNED: dict[str, Any] = {
    "verify_guest": {
        "verified": True,
        "guest_name": "Alex Rivera",
        "bookings": [{"booking_id": 1001, "booking_ref": "LRK-1001", "status": "confirmed"}],
    },
    "check_availability": {
        "rooms": [
            {"room_type": "Classic Queen", "nightly_rate": 189.0, "available": 3},
            {"room_type": "Garden King", "nightly_rate": 249.0, "available": 1},
        ]
    },
    "get_booking": {
        "booking_id": 1001,
        "room_type": "Classic Queen",
        "check_in": "2026-11-02",
        "check_out": "2026-11-05",
        "status": "confirmed",
        "total": 567.0,
    },
}

HoldResolution = Literal["approve", "reject", "timeout"]


class FakeGateway:
    """In-memory `ToolGateway`. Tests can steer holds with `hold_resolution`/`release()`."""

    def __init__(
        self,
        call_id: str,
        *,
        specs: list[ToolSpec] | None = None,
        hold_resolution: HoldResolution = "approve",
        approval_delay_s: float = 3.0,
        events: EventSink | None = None,
    ) -> None:
        self.call_id = call_id
        self._specs = specs if specs is not None else list(FAKE_TOOL_SPECS)
        self.hold_resolution: HoldResolution = hold_resolution
        self.approval_delay_s = approval_delay_s
        self._events = events
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.waits_started = 0
        self.waits_cancelled = 0
        self.closed = False
        self._release = asyncio.Event()

    def tool_specs(self) -> list[ToolSpec]:
        return list(self._specs)

    def release(self) -> None:
        """Resolve pending holds now instead of after `approval_delay_s`."""
        self._release.set()

    async def call(self, name: str, arguments: dict[str, Any]) -> ToolResult:
        self.calls.append((name, dict(arguments)))
        if self._events is not None:
            await self._events(
                GatewayEvent(call_id=self.call_id, kind="tool_requested", data={"tool": name})
            )
        tier = next((s.tier for s in self._specs if s.name == name), None)
        if tier is None or tier == "sensitive":
            return self._result(name, Decision.BLOCK, Outcome.NOT_RUN, "tool_denied")
        if tier == "money" and float(arguments.get("amount", 0)) > FAKE_HOLD_LIMIT:
            return self._result(name, Decision.HOLD, Outcome.PENDING, "rule_action_hold")
        return self._result(name, Decision.ALLOW, Outcome.RAN, None, arguments)

    async def wait(self, held: ToolResult, timeout_s: float = 60.0) -> ToolResult:
        self.waits_started += 1
        deadline_passed = False
        try:
            async with asyncio.timeout(min(timeout_s, self.approval_delay_s)):
                await self._release.wait()
        except TimeoutError:
            # The approver had not answered by the caller's deadline: that is a timeout,
            # whatever the approver would have said later.
            deadline_passed = timeout_s < self.approval_delay_s
        except asyncio.CancelledError:
            self.waits_cancelled += 1
            raise
        if self.hold_resolution == "approve" and not deadline_passed:
            args = next((a for n, a in reversed(self.calls) if n == held.tool), {})
            return self._result(held.tool, Decision.HOLD, Outcome.RAN, "approved", args)
        rejected = self.hold_resolution == "reject" and not deadline_passed
        reason = "rejected" if rejected else "approval_timeout"
        return self._result(held.tool, Decision.HOLD, Outcome.NOT_RUN, reason)

    async def close(self) -> None:
        self.closed = True

    def _result(
        self,
        name: str,
        decision: Decision,
        outcome: Outcome,
        reason: str | None,
        arguments: dict[str, Any] | None = None,
    ) -> ToolResult:
        if outcome is Outcome.RAN:
            content = json.dumps(_CANNED.get(name) or _money_row(name, arguments or {}))
        elif outcome is Outcome.PENDING:
            content = "Waiting for a manager's approval."
        else:
            content = "This action is not permitted, so it was not done."
        return ToolResult(
            tool=name,
            decision=decision,
            outcome=outcome,
            content=content,
            reason=reason,
            armoriq_mode="disabled",
        )


def _money_row(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    return {
        "payment_id": 9001,
        "kind": name,
        "booking_id": arguments.get("booking_id"),
        "amount": arguments.get("amount"),
        "status": "recorded",
    }


class FakeGatewayFactory:
    """`GatewayFactory` for the fake. Keeps the gateways it opened so tests can inspect them."""

    def __init__(self, **gateway_kwargs: Any) -> None:
        self._kwargs = gateway_kwargs
        self.opened: list[FakeGateway] = []

    async def open_call(self, call_id: str, events: EventSink | None = None) -> FakeGateway:
        gateway = FakeGateway(call_id, events=events, **self._kwargs)
        self.opened.append(gateway)
        return gateway


# What GATEWAY_FACTORY=countersign_agent.voice.fake_gateway:factory resolves to.
factory = FakeGatewayFactory()
