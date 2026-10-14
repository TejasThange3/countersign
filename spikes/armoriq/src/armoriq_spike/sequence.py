"""One governed tool call, in the exact order the SDK's Strands integration uses.

Source: armoriq_sdk/integrations/strands.py (v0.6.10)
    _on_after_model_call -> session.start_plan(tool_calls, goal)        (plan + intent token)
    _before_tool_call    -> session.check(tool, args, user_email)       (POST /iap/sdk/enforce)
                            hold -> await session.await_approval(...)   (GET /delegation/{id}/status)
    (tool runs)
    _on_after_tool_call  -> session.report(tool, args, result, opts)    (POST /iap/audit)

Fail-closed like Strands: the tool runs only on an explicit allow or an approved hold. Blocked,
rejected, timed-out and errored calls never run, so they are never reported as executed.
This is the shape the Countersign bridge will copy, with one change: every SDK network call
runs in a worker thread, including the hold wait. The SDK's await_approval blocks the event loop
on each poll, so it is replaced by approval.wait_for_approval (same loop, offloaded calls).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any, Literal, Protocol

from armoriq_sdk.session import EnforceResult, ReportOptions
from pydantic import BaseModel

from armoriq_spike.approval import ApprovalBackend, wait_for_approval

logger = logging.getLogger("armoriq_spike.sequence")

Outcome = Literal["ran", "blocked", "rejected", "timeout", "error"]
Executor = Callable[[str, dict[str, Any]], Awaitable[Any]]


class GovernedSession(Protocol):
    """The subset of armoriq_sdk.session.ArmorIQSession this flow uses."""

    def start_plan(self, tool_calls: list[dict[str, Any]], goal: str | None = None) -> Any: ...

    def check(
        self, tool_name: str, tool_args: dict[str, Any], user_email: str | None = None
    ) -> EnforceResult: ...

    def report(
        self,
        tool_name: str,
        tool_args: dict[str, Any],
        result: Any,
        opts: ReportOptions | None = None,
    ) -> None: ...


class CallRecord(BaseModel):
    """What happened to one tool call; printed by smoke.py and kept as evidence."""

    tool: str
    user_email: str
    decision: str  # first ArmorIQ answer: allow | hold | block | error
    outcome: Outcome
    plan_id: str | None = None
    delegation_id: str | None = None
    approval: str | None = None  # approved | rejected | timeout (holds only)
    reason: str | None = None
    matched_policy: str | None = None
    result: Any = None


def _plan_id(token: Any) -> str | None:
    return getattr(token, "plan_id", None)


async def governed_call(
    session: GovernedSession,
    *,
    approvals: ApprovalBackend,  # the ArmorIQClient; polled in a thread while a call is held
    tool_name: str,
    args: dict[str, Any],
    user_email: str,
    goal: str,
    execute: Executor,
    approval_wait_seconds: float,
    approval_poll_seconds: float,
    # Awaited before polling starts: the voice agent speaks its "one moment" line here, and the
    # eval approver decides the delegation here.
    on_hold: Callable[[CallRecord], Awaitable[None]] | None = None,
) -> CallRecord:
    """Never raises for ArmorIQ or tool failures: every path returns a CallRecord, and the tool
    runs only on an explicit allow or an approved hold."""
    record = CallRecord(tool=tool_name, user_email=user_email, decision="error", outcome="error")

    # The SDK's start_plan/check/report are blocking httpx calls; keep them off the event loop.
    try:
        token = await asyncio.to_thread(
            session.start_plan, [{"name": tool_name, "args": args}], goal
        )
    except Exception as exc:
        # Strands logs a failed capture and lets check() fail closed ("called before
        # start_plan" / tool-not-in-plan). Same outcome here, without the extra HTTP call.
        logger.exception("plan capture failed for %s", tool_name)
        record.reason = f"plan capture failed (fail-closed): {exc}"
        return record
    record.plan_id = _plan_id(token)

    try:
        decision = await asyncio.to_thread(session.check, tool_name, args, user_email)
    except Exception as exc:  # fail closed, exactly like Strands
        logger.exception("enforcement error for %s", tool_name)
        record.reason = f"enforcement error (fail-closed): {exc}"
        return record

    record.decision = decision.action
    record.reason = decision.reason
    record.matched_policy = decision.matched_policy
    record.delegation_id = decision.delegation_id

    if not decision.allowed:
        if decision.action != "hold":
            record.outcome = "blocked"
            return record
        if not decision.delegation_id:
            # The SDK still returns hold when creating the delegation failed; nothing to approve.
            record.reason = f"{decision.reason or 'hold'} (no delegation id: request not created)"
            return record
        try:
            if on_hold is not None:
                await on_hold(record)
            approval = await wait_for_approval(
                approvals,
                decision.delegation_id,
                user_email=user_email,
                plan_id=record.plan_id,
                timeout_seconds=approval_wait_seconds,
                interval=approval_poll_seconds,
            )
        except Exception as exc:  # Strands' hold wait sits inside its fail-closed try too
            logger.exception("approval wait failed for %s", tool_name)
            record.reason = f"approval wait error (fail-closed): {exc}"
            return record
        record.approval = approval
        if approval != "approved":
            record.outcome = "rejected" if approval == "rejected" else "timeout"
            return record

    try:
        record.result = await execute(tool_name, args)
    except Exception as exc:
        # The tool ran and failed: still report it, as Strands does.
        record.outcome = "error"
        record.reason = f"tool error: {exc}"
        await _report(
            session,
            tool_name,
            args,
            str(exc),
            ReportOptions(status="error", error_message=str(exc)),
        )
        return record

    record.outcome = "ran"
    await _report(session, tool_name, args, record.result, ReportOptions(status="success"))
    return record


async def _report(
    session: GovernedSession,
    tool_name: str,
    args: dict[str, Any],
    result: Any,
    opts: ReportOptions,
) -> None:
    """Best-effort audit, like Strands: the tool already ran, so a failed report must never
    turn a completed action (say, an issued refund) into an apparent failure."""
    try:
        await asyncio.to_thread(session.report, tool_name, args, result, opts)
    except Exception:
        logger.warning("execution report failed for %s", tool_name, exc_info=True)
