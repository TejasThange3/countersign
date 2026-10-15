"""Live proof: the real bridge against live ArmorIQ and the real hotel-mcp. Never run by check.py.

    uv run --project apps/agent pytest -m live tests/bridge/test_live_bridge.py -s

Needs: hotel-mcp running at MCP_URL (seeded), the `countersign` policy configured in the
console (docs/research/armoriq-policy-countersign.md: unverified read only; guest read +
write, money always hold, sensitive block), and ARMORIQ_ADMIN_EMAIL in .env (approves the $40
hold, rejects the $250 one). Saves masked evidence JSON with the plan ids under
tests/bridge/evidence/.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path
from typing import Any, Literal

import httpx
import pytest
from countersign_agent.bridge import BridgeSettings, GovernedGateway, GovernedGatewayFactory
from countersign_agent.bridge.delegation import decide_delegation, fetch_approver_role
from countersign_agent.contracts import Decision, GatewayEvent, Outcome, ToolResult

pytestmark = pytest.mark.live

EVIDENCE_DIR = Path(__file__).parent / "evidence"
BOOKING_REF, LAST_NAME = "LRK-1001", "Okafor"  # seeded demo guest
BACKEND = "https://api.armoriq.ai"


async def test_live_bridge_decisions() -> None:
    settings = BridgeSettings()
    assert not settings.disable_armoriq, "live proof must run with ArmorIQ enabled"
    factory = GovernedGatewayFactory(settings)
    events: list[GatewayEvent] = []
    cases: list[dict[str, Any]] = []

    async def sink(event: GatewayEvent) -> None:
        events.append(event)

    def record(case: str, expected: str, result: ToolResult, **extra: Any) -> None:
        cases.append(
            {"case": case, "expected": expected, **result.model_dump(mode="json"), **extra}
        )

    gw: GovernedGateway = await factory.open_call("live-proof", events=sink)
    try:
        assert gw.mode == "live"

        # 1. Unverified caller asks for a refund: ArmorIQ blocks (not the bridge).
        refund40 = {"booking_id": 1, "amount": 40, "reason": "live proof: unverified"}
        unverified = await gw.call("issue_refund", refund40)
        record("unverified refund", "BLOCK", unverified)
        assert unverified.decision is Decision.BLOCK, unverified
        assert unverified.reason != "not_verified", "ArmorIQ must be the one that blocked"

        # Verify (itself governed), then find the guest's booking id.
        verify = await gw.call("verify_guest", {"booking_ref": BOOKING_REF, "last_name": LAST_NAME})
        record("verify_guest", "ALLOW", verify)
        assert verify.outcome is Outcome.RAN, verify
        bookings = json.loads(verify.content)["bookings"]
        booking_id = next(b["booking_id"] for b in bookings if b["ref"] == BOOKING_REF)

        # 2. Verified $40 refund: money always holds (ArmorIQ has no working amount limit),
        # approved over the API by the admin, then written.
        small = await gw.call(
            "issue_refund", {"booking_id": booking_id, "amount": 40, "reason": "live proof: $40"}
        )
        record("verified $40 refund (held)", "HOLD", small)
        assert small.decision is Decision.HOLD and small.outcome is Outcome.PENDING, small
        assert small.delegation_id
        approval = await _decide(settings, small.delegation_id, "approve")
        approved = await gw.wait(small, timeout_s=90)
        small_row = json.loads(approved.content) if approved.outcome is Outcome.RAN else None
        record(
            "verified $40 refund (after approval)",
            "RAN",
            approved,
            approver_status=approval,
            row=small_row,
        )
        assert approved.outcome is Outcome.RAN, approved
        assert small_row is not None and small_row["amount"] == 40
        assert small_row["payment_id"] in await _payment_ids(gw, booking_id)

        # 3. Verified $250 refund: held, rejected by the admin, so nothing is written.
        before = await _payment_ids(gw, booking_id)
        big = await gw.call(
            "issue_refund", {"booking_id": booking_id, "amount": 250, "reason": "live proof: $250"}
        )
        record("verified $250 refund (held)", "HOLD", big)
        assert big.decision is Decision.HOLD and big.outcome is Outcome.PENDING, big
        assert big.delegation_id
        rejection = await _decide(settings, big.delegation_id, "reject")
        rejected = await gw.wait(big, timeout_s=90)
        after = await _payment_ids(gw, booking_id)
        record(
            "verified $250 refund (after rejection)",
            "NOT_RUN",
            rejected,
            approver_status=rejection,
            new_payments=sorted(after - before),
        )
        assert rejected.outcome is Outcome.NOT_RUN and rejected.reason == "rejected", rejected
        assert after == before, "a rejected refund must not write a row"

        # 4. Sensitive export: blocked even for a verified guest.
        export = await gw.call("export_guest_list", {})
        record("export_guest_list", "BLOCK", export)
        assert export.decision is Decision.BLOCK, export
        assert export.reason != "unknown_tool"
    finally:
        await gw.close()
        _save_evidence(factory, cases, events)


async def _payment_ids(gw: GovernedGateway, booking_id: int) -> set[int]:
    """Read the booking back through the governed path (a guest read, allowed)."""
    booking = await gw.call("get_booking", {"booking_id": booking_id})
    assert booking.outcome is Outcome.RAN, booking
    return {p["payment_id"] for p in json.loads(booking.content)["payments"]}


async def _decide(
    settings: BridgeSettings, delegation_id: str, decision: Literal["approve", "reject"]
) -> int:
    headers = {"X-API-Key": settings.require_api_key()}
    async with httpx.AsyncClient() as http:
        role = await fetch_approver_role(http, BACKEND, headers, settings.armoriq_admin_email)
        result = await decide_delegation(
            http,
            BACKEND,
            delegation_id,
            headers,
            settings.armoriq_admin_email,
            decision,
            role,
        )
    assert result.ok, f"{decision} failed: HTTP {result.status_code}"
    return result.status_code


def _save_evidence(
    factory: GovernedGatewayFactory, cases: list[dict[str, Any]], events: list[GatewayEvent]
) -> None:
    EVIDENCE_DIR.mkdir(exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    evidence = {
        "armoriq_mode": "live",
        "armoriq_sdk": version("armoriq-sdk"),
        "backend": BACKEND,
        "recorded_at": stamp,
        "cases": cases,
        "events": [e.model_dump(mode="json") for e in events],
    }
    path = EVIDENCE_DIR / f"{stamp}-live-bridge.json"
    path.write_text(json.dumps(factory.masker.clean(evidence), indent=2), encoding="utf-8")
    print(f"\nevidence saved: {path}")
