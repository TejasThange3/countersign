"""GovernedGateway against fake ArmorIQ and fake hotel-mcp: identity, injection, decisions,
holds, baseline mode and events."""

from __future__ import annotations

import asyncio
import json
import time

import pytest
from armoriq_sdk.exceptions import DelegationException
from armoriq_sdk.session import EnforceResult
from countersign_agent.bridge.enforcer import DisabledEnforcer, UnavailableEnforcer
from countersign_agent.bridge.executor import ToolOutput
from countersign_agent.bridge.gateway import GovernedGateway
from countersign_agent.contracts import Decision, Outcome

from .fakes import (
    GUEST,
    GUEST_ID,
    NOT_VERIFIED,
    OTHER_GUEST_ID,
    UNVERIFIED,
    VERIFIED_OTHER,
    FakeApprovals,
    FakeMCP,
    Harness,
    fake_allow,
)

REFUND = {"booking_id": 1, "amount": 40, "reason": "noisy room"}
BIG_REFUND = {"booking_id": 1, "amount": 250, "reason": "noisy room"}
VERIFY = {"booking_ref": "LRK-1001", "last_name": "Okafor"}


async def verified(h: Harness) -> GovernedGateway:
    gw = await h.open()
    result = await gw.call("verify_guest", VERIFY)
    assert result.outcome is Outcome.RAN
    return gw


# --- tool specs ---


async def test_specs_hide_guest_id_but_keep_target_guest_id() -> None:
    gw = await Harness().open()
    specs = {s.name: s for s in gw.tool_specs()}
    refund = specs["issue_refund"].parameters
    assert "guest_id" not in refund["properties"]
    assert "guest_id" not in refund["required"]
    assert specs["issue_refund"].tier == "money"
    assert "target_guest_id" in specs["delete_guest_profile"].parameters["properties"]


# --- plan and identity ---


async def test_call_opens_one_unverified_session_declaring_every_tool() -> None:
    h = Harness()
    gw = await h.open()
    assert len(h.log.plans) == 1
    user, tools, goal = h.log.plans[0]
    assert user == UNVERIFIED
    assert set(tools) == {s.name for s in gw.tool_specs()}
    assert goal is not None and "call-1" in goal


async def test_verify_switches_identity_and_replans_once() -> None:
    h = Harness()
    gw = await verified(h)
    assert [p[0] for p in h.log.plans] == [UNVERIFIED, GUEST]
    assert h.sessions[0].closed  # the unverified session is retired
    # verify_guest itself went through ArmorIQ, as the unverified identity.
    assert h.log.checks[0][:2] == (UNVERIFIED, "verify_guest")
    changed = [e for e in h.events if e.kind == "identity_changed"]
    assert len(changed) == 1
    assert changed[0].data["guest_id"] == GUEST_ID
    assert changed[0].data["plan_id"] == "plan-2"
    # Later calls are checked as the guest.
    await gw.call("get_hotel_info", {})
    assert h.log.checks[-1][0] == GUEST


async def test_verify_result_never_shows_guest_id_to_the_llm() -> None:
    h = Harness()
    gw = await h.open()
    result = await gw.call("verify_guest", VERIFY)
    assert "guest_id" not in json.loads(result.content)


async def test_failed_verify_keeps_caller_unverified() -> None:
    h = Harness(mcp=FakeMCP({"verify_guest": NOT_VERIFIED}))
    gw = await h.open()
    result = await gw.call("verify_guest", VERIFY)
    assert result.outcome is Outcome.RAN
    assert len(h.log.plans) == 1
    assert "identity_changed" not in h.kinds()


async def test_verify_lockout_after_max_failures_never_reaches_mcp_or_armoriq() -> None:
    h = Harness(mcp=FakeMCP({"verify_guest": NOT_VERIFIED}), max_failed_verifies=3)
    gw = await h.open()
    for _ in range(3):
        await gw.call("verify_guest", VERIFY)
    mcp_calls, checks = len(h.mcp.calls), len(h.log.checks)

    h.mcp.answers["verify_guest"] = VERIFIED_OTHER  # even the right answer is too late now
    result = await gw.call("verify_guest", VERIFY)
    assert result.decision is Decision.BLOCK
    assert result.outcome is Outcome.NOT_RUN
    assert result.reason == "verify_locked_out"
    assert len(h.mcp.calls) == mcp_calls
    assert len(h.log.checks) == checks


async def test_reverify_as_same_guest_is_a_no_op() -> None:
    h = Harness()
    gw = await verified(h)
    again = await gw.call("verify_guest", VERIFY)
    assert again.outcome is Outcome.RAN
    assert len(h.log.plans) == 2
    assert h.kinds().count("identity_changed") == 1


async def test_reverify_as_another_guest_is_refused_and_details_withheld() -> None:
    h = Harness()
    gw = await verified(h)
    h.mcp.answers["verify_guest"] = VERIFIED_OTHER
    result = await gw.call("verify_guest", {"booking_ref": "LRK-1002", "last_name": "Brandt"})
    assert result.reason == "other_guest"
    assert "Bo" not in result.content and str(OTHER_GUEST_ID) not in result.content
    assert len(h.log.plans) == 2
    # Still the first guest.
    await gw.call("issue_refund", REFUND)
    assert h.mcp.calls[-1][1]["guest_id"] == GUEST_ID


async def test_blocked_verify_does_not_run() -> None:
    def block_verify(tool: str, args: dict[str, object]) -> EnforceResult:
        return EnforceResult(allowed=False, action="block", reason="tool_denied")

    h = Harness(decide=block_verify)
    gw = await h.open()
    result = await gw.call("verify_guest", VERIFY)
    assert result.outcome is Outcome.NOT_RUN
    assert h.mcp.calls == []


# --- guest_id injection ---


async def test_verified_guest_id_overwrites_whatever_the_model_sent() -> None:
    h = Harness()
    gw = await verified(h)
    await gw.call("issue_refund", {**REFUND, "guest_id": 999})
    name, args = h.mcp.calls[-1]
    assert name == "issue_refund"
    assert args["guest_id"] == GUEST_ID
    # ArmorIQ judged the same arguments that ran.
    assert h.log.checks[-1][2]["guest_id"] == GUEST_ID


async def test_guest_id_is_inserted_when_the_model_omits_it() -> None:
    h = Harness()
    gw = await verified(h)
    await gw.call("get_booking", {"booking_id": 1})
    assert h.mcp.calls[-1][1] == {"booking_id": 1, "guest_id": GUEST_ID}


async def test_guest_id_is_dropped_for_tools_that_do_not_take_it() -> None:
    h = Harness(decide=fake_allow)
    gw = await verified(h)
    await gw.call("get_hotel_info", {"guest_id": 999})
    assert h.mcp.calls[-1] == ("get_hotel_info", {})


async def test_target_guest_id_is_left_untouched() -> None:
    h = Harness(decide=fake_allow)
    gw = await verified(h)
    await gw.call("delete_guest_profile", {"target_guest_id": 3, "guest_id": 999})
    assert h.log.checks[-1][2] == {"target_guest_id": 3}
    assert h.mcp.calls[-1] == ("delete_guest_profile", {"target_guest_id": 3})


async def test_unverified_guest_scoped_tool_is_refused_even_if_armoriq_allows() -> None:
    h = Harness(decide=fake_allow)
    gw = await h.open()
    result = await gw.call("get_booking", {"booking_id": 1, "guest_id": 999})
    assert result.decision is Decision.BLOCK
    assert result.outcome is Outcome.NOT_RUN
    assert result.reason == "not_verified"
    assert h.mcp.calls == []
    assert h.log.checks[-1][2] == {"booking_id": 1}  # ArmorIQ was still asked first


# --- decisions ---


async def test_allow_runs_and_reports() -> None:
    h = Harness()
    gw = await verified(h)
    result = await gw.call("issue_refund", REFUND)
    assert result.decision is Decision.ALLOW
    assert result.outcome is Outcome.RAN
    assert json.loads(result.content) == {"payment_id": 1, "amount": 40}
    assert result.plan_id == "plan-2"
    assert result.armoriq_mode == "live"
    assert h.log.reports[-1] == ("issue_refund", "success")


async def test_block_never_runs_and_says_nothing_about_policy() -> None:
    h = Harness()
    gw = await verified(h)
    result = await gw.call("export_guest_list", {})
    assert result.decision is Decision.BLOCK
    assert result.outcome is Outcome.NOT_RUN
    assert result.content == "I can't do that."
    assert result.reason == "tool_denied" and result.policy == "fake-policy"
    assert ("export_guest_list", {}) not in h.mcp.calls
    assert all(r[0] != "export_guest_list" for r in h.log.reports)


async def test_unknown_tool_is_refused_without_armoriq_or_mcp() -> None:
    h = Harness()
    gw = await h.open()
    result = await gw.call("ghost_tool", {})
    assert result.reason == "unknown_tool"
    assert h.log.checks == [] and h.mcp.calls == []


async def test_tool_error_is_reported_and_shown() -> None:
    h = Harness(mcp=FakeMCP({"issue_refund": ToolOutput(data="booking not found", is_error=True)}))
    gw = await verified(h)
    result = await gw.call("issue_refund", REFUND)
    assert result.outcome is Outcome.ERROR
    assert result.content == "booking not found"
    assert h.log.reports[-1] == ("issue_refund", "error")


async def test_mcp_connection_failure_is_an_error_not_a_crash() -> None:
    h = Harness(mcp=FakeMCP({"issue_refund": ConnectionError("fake: hotel-mcp down")}))
    gw = await verified(h)
    result = await gw.call("issue_refund", REFUND)
    assert result.outcome is Outcome.ERROR
    assert "hotel-mcp" not in result.content


# --- unavailable (fail closed) ---


async def test_check_exception_is_unavailable() -> None:
    def broken(tool: str, args: dict[str, object]) -> EnforceResult:
        raise RuntimeError("fake: network down")

    h = Harness(decide=broken)
    gw = await h.open()
    result = await gw.call("get_hotel_info", {})
    assert result.decision is Decision.UNAVAILABLE
    assert result.outcome is Outcome.NOT_RUN
    assert result.content == "I can't do that right now."
    assert h.mcp.calls == []


async def test_sdk_enforce_unavailable_block_is_unavailable() -> None:
    def sdk_swallowed(tool: str, args: dict[str, object]) -> EnforceResult:
        return EnforceResult(
            allowed=False, action="block", reason="enforce-unavailable: fake timeout"
        )

    gw = await Harness(decide=sdk_swallowed).open()
    result = await gw.call("get_hotel_info", {})
    assert result.decision is Decision.UNAVAILABLE
    assert result.reason == "enforce_unavailable"


async def test_hold_without_delegation_is_unavailable() -> None:
    def hold_no_id(tool: str, args: dict[str, object]) -> EnforceResult:
        return EnforceResult(allowed=False, action="hold", reason="rule_action_hold")

    h = Harness(decide=hold_no_id)
    gw = await h.open()
    result = await gw.call("get_hotel_info", {})
    assert result.decision is Decision.UNAVAILABLE
    assert result.outcome is Outcome.NOT_RUN
    assert h.mcp.calls == []


async def test_failed_plan_makes_every_call_unavailable() -> None:
    h = Harness()
    h.log.fail_plan = True
    gw = await h.open()
    result = await gw.call("get_hotel_info", {})
    assert result.decision is Decision.UNAVAILABLE
    assert result.reason == "no_plan"
    assert h.mcp.calls == []


async def test_failed_replan_after_verify_fails_closed() -> None:
    h = Harness()
    gw = await h.open()
    h.log.fail_plan = True
    await gw.call("verify_guest", VERIFY)
    result = await gw.call("issue_refund", REFUND)
    assert result.decision is Decision.UNAVAILABLE
    assert ("issue_refund", {**REFUND, "guest_id": GUEST_ID}) not in h.mcp.calls


async def test_unreachable_armoriq_fails_every_call_closed() -> None:
    h = Harness()
    gw = await h.open(enforcer=UnavailableEnforcer())
    result = await gw.call("get_hotel_info", {})
    assert result.decision is Decision.UNAVAILABLE
    assert result.armoriq_mode == "live"
    assert h.mcp.calls == []


# --- holds ---


async def test_hold_returns_pending_at_once_with_ids() -> None:
    h = Harness()
    gw = await verified(h)
    result = await gw.call("issue_refund", BIG_REFUND)
    assert result.decision is Decision.HOLD
    assert result.outcome is Outcome.PENDING
    assert result.delegation_id == "d-1"
    assert result.plan_id == "plan-2"
    assert result.content == "That needs a manager's approval. One moment."
    assert h.mcp.calls[-1][0] == "verify_guest"  # nothing ran yet
    assert h.approvals.polls == 0  # and nobody is polling yet


async def test_hold_then_approve_runs_once_and_marks_executed() -> None:
    h = Harness(approvals=FakeApprovals(["pending", "approved"]))
    gw = await verified(h)
    held = await gw.call("issue_refund", BIG_REFUND)
    result = await gw.wait(held, timeout_s=2)
    assert result.decision is Decision.HOLD
    assert result.outcome is Outcome.RAN
    assert result.reason == "approved"
    assert h.mcp.calls[-1] == ("issue_refund", {**BIG_REFUND, "guest_id": GUEST_ID})
    assert h.approvals.marked == [(GUEST, "d-1", "plan-2")]
    assert h.log.reports[-1] == ("issue_refund", "success")
    resolved = [e for e in h.events if e.kind == "hold_resolved"]
    assert resolved[0].data["resolution"] == "approved"
    # The hold is consumed: waiting again can't run it twice.
    again = await gw.wait(held, timeout_s=0.1)
    assert again.outcome is Outcome.NOT_RUN
    assert sum(1 for c in h.mcp.calls if c[0] == "issue_refund") == 1


@pytest.mark.parametrize(
    ("statuses", "reason", "say"),
    [
        (["pending", "rejected"], "rejected", "The manager didn't approve that."),
        (["pending"], "timeout", "I couldn't get a manager's approval in time."),
    ],
)
async def test_hold_rejected_or_timed_out_never_runs(
    statuses: list[str | Exception], reason: str, say: str
) -> None:
    h = Harness(approvals=FakeApprovals(statuses))
    gw = await verified(h)
    held = await gw.call("issue_refund", BIG_REFUND)
    result = await gw.wait(held, timeout_s=0.1)
    assert result.outcome is Outcome.NOT_RUN
    assert result.reason == reason
    assert result.content == say
    assert all(c[0] != "issue_refund" for c in h.mcp.calls)
    assert all(r[0] != "issue_refund" for r in h.log.reports)


async def test_approval_error_fails_closed() -> None:
    forbidden = DelegationException("fake 403", delegation_id="d-1", status_code=403)
    h = Harness(approvals=FakeApprovals([forbidden]))
    gw = await verified(h)
    held = await gw.call("issue_refund", BIG_REFUND)
    result = await gw.wait(held, timeout_s=1)
    assert result.decision is Decision.UNAVAILABLE
    assert result.outcome is Outcome.NOT_RUN
    assert all(c[0] != "issue_refund" for c in h.mcp.calls)


async def test_cancelling_the_wait_stops_polling_and_never_runs() -> None:
    h = Harness(approvals=FakeApprovals(["pending"]))
    gw = await verified(h)
    held = await gw.call("issue_refund", BIG_REFUND)
    task = asyncio.create_task(gw.wait(held, timeout_s=10))
    await asyncio.sleep(0.05)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    polls = h.approvals.polls
    h.approvals.statuses = ["approved"]  # a late approval must not matter
    await asyncio.sleep(0.05)
    assert h.approvals.polls == polls
    assert all(c[0] != "issue_refund" for c in h.mcp.calls)
    assert [e.data["resolution"] for e in h.events if e.kind == "hold_resolved"] == ["cancelled"]


async def test_verify_while_a_hold_is_pending_does_not_replan() -> None:
    """A re-plan drops pending approvals, so the identity can't change under a hold."""

    def hold_everything_but_verify(tool: str, args: dict[str, object]) -> EnforceResult:
        if tool == "verify_guest":
            return EnforceResult(allowed=True, action="allow")
        return EnforceResult(allowed=False, action="hold", delegation_id="d-9")

    h = Harness(decide=hold_everything_but_verify)
    gw = await h.open()
    held = await gw.call("get_hotel_info", {})
    assert held.outcome is Outcome.PENDING
    result = await gw.call("verify_guest", VERIFY)
    assert result.reason == "hold_pending"
    assert len(h.log.plans) == 1
    assert all(c[0] != "verify_guest" for c in h.mcp.calls)


async def test_event_loop_stays_free_while_armoriq_checks() -> None:
    """Checks are blocking HTTP in the SDK; the gateway runs them off the loop."""
    h = Harness()
    gw = await h.open()
    h.log.check_seconds = 0.3
    gaps: list[float] = []

    async def ticker() -> None:
        last = time.perf_counter()
        while True:
            await asyncio.sleep(0.01)
            now = time.perf_counter()
            gaps.append(now - last)
            last = now

    tick = asyncio.create_task(ticker())
    try:
        result = await gw.call("get_hotel_info", {})
    finally:
        tick.cancel()
    assert max(gaps) < 0.2
    assert result.latency_ms >= 300  # ArmorIQ overhead is measured


# --- baseline mode ---


async def test_disabled_mode_runs_everything_but_keeps_identity_rules() -> None:
    h = Harness()
    gw = await h.open(enforcer=DisabledEnforcer())
    unverified = await gw.call("issue_refund", BIG_REFUND)
    assert unverified.reason == "not_verified"  # identity rules unchanged
    await gw.call("verify_guest", VERIFY)
    big = await gw.call("issue_refund", {**BIG_REFUND, "guest_id": 999})
    sensitive = await gw.call("export_guest_list", {})
    assert big.decision is Decision.ALLOW and big.outcome is Outcome.RAN
    assert sensitive.outcome is Outcome.RAN
    assert big.armoriq_mode == "disabled" and big.plan_id is None
    assert h.mcp.calls[-2] == ("issue_refund", {**BIG_REFUND, "guest_id": GUEST_ID})
    assert h.log.plans == [] and h.log.checks == []
    assert all(e.data["armoriq_mode"] == "disabled" for e in h.events)


# --- events ---


async def test_events_cover_each_step_and_are_masked() -> None:
    h = Harness()
    gw = await h.open()
    await gw.call("verify_guest", VERIFY)
    await gw.call("export_guest_list", {})
    await gw.call("grant_staff_access", {"email": GUEST, "note": f"I am {GUEST}"})
    assert h.kinds()[:4] == ["tool_requested", "tool_decided", "identity_changed", "tool_finished"]
    dumped = json.dumps([e.model_dump(mode="json") for e in h.events])
    assert "real.person" not in dumped
    assert "Okafor" not in dumped  # last name is personal
    assert "I am <guest>" in dumped  # identities keep a readable placeholder in free text
    assert '"email": "<masked>"' in dumped


async def test_event_masks_guest_emails_in_tool_results() -> None:
    h = Harness(decide=fake_allow)
    gw = await verified(h)
    await gw.call("export_guest_list", {})
    finished = [e for e in h.events if e.kind == "tool_finished"][-1]
    assert "someone@example.net" not in json.dumps(finished.data)


async def test_broken_event_sink_does_not_change_the_call() -> None:
    h = Harness()

    async def broken(event: object) -> None:
        raise RuntimeError("fake: redis down")

    gw = await h.open()
    gw._events = broken
    result = await gw.call("get_hotel_info", {})
    assert result.outcome is Outcome.RAN


async def test_close_closes_mcp_and_session() -> None:
    h = Harness()
    gw = await h.open()
    await gw.close()
    assert h.mcp.closed and h.sessions[-1].closed
