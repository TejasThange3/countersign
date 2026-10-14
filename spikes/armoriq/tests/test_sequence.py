"""Unit tests for governed_call. FakeArmorIQSession is a fake: no ArmorIQ is contacted."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest
from armoriq_sdk.session import EnforceResult, ReportOptions
from armoriq_spike.sequence import CallRecord, governed_call


@dataclass
class FakeToken:
    plan_id: str = "fake-plan-1"


@dataclass
class FakeArmorIQSession:
    """Fake of ArmorIQSession: returns a scripted decision and records every call in order."""

    decision: EnforceResult | Exception
    approval: str | Exception = "approved"
    plan_error: Exception | None = None
    report_error: Exception | None = None
    marked_plan_id: str | None = None
    calls: list[str] = field(default_factory=list)
    reports: list[tuple[str, Any, ReportOptions | None]] = field(default_factory=list)

    def start_plan(self, tool_calls: list[dict[str, Any]], goal: str | None = None) -> FakeToken:
        self.calls.append("start_plan")
        if self.plan_error is not None:
            raise self.plan_error
        return FakeToken()

    def check(
        self, tool_name: str, tool_args: dict[str, Any], user_email: str | None = None
    ) -> EnforceResult:
        self.calls.append("check")
        if isinstance(self.decision, Exception):
            raise self.decision
        return self.decision

    # The fake also plays the ApprovalBackend (ArmorIQClient) so one ordered call log covers
    # plan -> check -> poll -> mark_executed -> report.
    def get_delegation_status(self, delegation_id: str) -> str:
        self.calls.append("poll")
        if isinstance(self.approval, Exception):
            raise self.approval
        # "timeout" means nobody decides: keep answering pending until the wait runs out.
        return "pending" if self.approval == "timeout" else self.approval

    def mark_delegation_executed(
        self, user_email: str, delegation_id: str, plan_id: str | None = None
    ) -> None:
        self.calls.append("mark_executed")
        self.marked_plan_id = plan_id

    def report(
        self,
        tool_name: str,
        tool_args: dict[str, Any],
        result: Any,
        opts: ReportOptions | None = None,
    ) -> None:
        self.calls.append("report")
        self.reports.append((tool_name, result, opts))
        if self.report_error is not None:
            raise self.report_error


class FakeExecutor:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.ran: list[str] = []

    async def __call__(self, tool_name: str, args: dict[str, Any]) -> Any:
        self.ran.append(tool_name)
        if self.fail:
            raise RuntimeError("tool exploded")
        return {"ok": True}


async def run(session: FakeArmorIQSession, executor: FakeExecutor, **kw: Any) -> CallRecord:
    return await governed_call(
        session,
        approvals=session,
        tool_name="issue_refund",
        args={"booking_id": "b1", "amount": 250, "reason": "test"},
        user_email="voice-guest@example.com",
        goal="smoke",
        execute=executor,
        approval_wait_seconds=1,
        approval_poll_seconds=0.01,
        **kw,
    )


ALLOW = EnforceResult(allowed=True, action="allow", matched_policy="p")
BLOCK = EnforceResult(allowed=False, action="block", reason="denied", matched_policy="p")
HOLD = EnforceResult(allowed=False, action="hold", reason="above 100", delegation_id="d1")


async def test_allow_runs_tool_then_reports_success() -> None:
    session, executor = FakeArmorIQSession(ALLOW), FakeExecutor()
    record = await run(session, executor)
    assert record.outcome == "ran"
    assert record.decision == "allow"
    assert record.plan_id == "fake-plan-1"
    assert session.calls == ["start_plan", "check", "report"]
    assert executor.ran == ["issue_refund"]
    assert session.reports[0][2] is not None and session.reports[0][2].status == "success"


async def test_block_never_runs_and_never_reports() -> None:
    session, executor = FakeArmorIQSession(BLOCK), FakeExecutor()
    record = await run(session, executor)
    assert record.outcome == "blocked"
    assert record.reason == "denied"
    assert executor.ran == []
    assert "report" not in session.calls


async def test_hold_approved_waits_then_runs_and_reports() -> None:
    held: list[CallRecord] = []
    session, executor = FakeArmorIQSession(HOLD, approval="approved"), FakeExecutor()

    async def remember(record: CallRecord) -> None:
        held.append(record)

    record = await run(session, executor, on_hold=remember)
    assert record.decision == "hold"
    assert record.approval == "approved"
    assert record.outcome == "ran"
    assert record.delegation_id == "d1"
    assert session.calls == ["start_plan", "check", "poll", "mark_executed", "report"]
    assert session.marked_plan_id == "fake-plan-1"
    assert len(held) == 1


@pytest.mark.parametrize(
    ("approval", "outcome"), [("rejected", "rejected"), ("timeout", "timeout")]
)
async def test_hold_not_approved_never_runs(approval: str, outcome: str) -> None:
    session, executor = FakeArmorIQSession(HOLD, approval=approval), FakeExecutor()
    record = await run(session, executor)
    assert record.outcome == outcome
    assert executor.ran == []
    assert "report" not in session.calls


async def test_hold_without_delegation_id_fails_closed_without_waiting() -> None:
    hold = EnforceResult(allowed=False, action="hold", reason="above 100", delegation_id=None)
    session, executor = FakeArmorIQSession(hold), FakeExecutor()
    record = await run(session, executor)
    assert record.outcome == "error"
    assert session.calls == ["start_plan", "check"]
    assert executor.ran == []


async def test_enforcement_exception_fails_closed() -> None:
    session, executor = FakeArmorIQSession(RuntimeError("network down")), FakeExecutor()
    record = await run(session, executor)
    assert record.outcome == "error"
    assert record.reason is not None and "network down" in record.reason
    assert executor.ran == []


async def test_tool_failure_is_reported_as_error() -> None:
    session, executor = FakeArmorIQSession(ALLOW), FakeExecutor(fail=True)
    record = await run(session, executor)
    assert record.outcome == "error"
    opts = session.reports[0][2]
    assert opts is not None and opts.status == "error"


async def test_plan_capture_failure_fails_closed_without_checking() -> None:
    session = FakeArmorIQSession(ALLOW, plan_error=RuntimeError("token endpoint down"))
    executor = FakeExecutor()
    record = await run(session, executor)
    assert record.outcome == "error"
    assert record.plan_id is None
    assert record.reason is not None and "token endpoint down" in record.reason
    assert session.calls == ["start_plan"]
    assert executor.ran == []


async def test_approval_wait_error_fails_closed() -> None:
    session = FakeArmorIQSession(HOLD, approval=RuntimeError("status 500"))
    executor = FakeExecutor()
    record = await run(session, executor)
    assert record.outcome == "error"
    assert record.decision == "hold"
    assert executor.ran == []
    assert "report" not in session.calls


async def test_on_hold_error_fails_closed_without_polling() -> None:
    async def broken(record: CallRecord) -> None:
        raise RuntimeError("tts down")

    session, executor = FakeArmorIQSession(HOLD), FakeExecutor()
    record = await run(session, executor, on_hold=broken)
    assert record.outcome == "error"
    assert "poll" not in session.calls
    assert executor.ran == []


async def test_report_failure_after_tool_ran_keeps_the_result() -> None:
    # The refund already happened; a failed audit POST must not hide that.
    session = FakeArmorIQSession(ALLOW, report_error=RuntimeError("audit 503"))
    executor = FakeExecutor()
    record = await run(session, executor)
    assert record.outcome == "ran"
    assert record.result == {"ok": True}
    assert session.calls == ["start_plan", "check", "report"]


async def test_report_failure_after_tool_error_keeps_the_error() -> None:
    session = FakeArmorIQSession(ALLOW, report_error=RuntimeError("audit 503"))
    executor = FakeExecutor(fail=True)
    record = await run(session, executor)
    assert record.outcome == "error"
    assert record.reason is not None and "tool exploded" in record.reason
