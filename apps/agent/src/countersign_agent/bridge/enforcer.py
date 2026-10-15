"""The ArmorIQ side of a governed call: plan, check, wait for approval, report.

`ArmorIQEnforcer` follows the Strands adapter's order (docs/research/armoriq-call-sequence.md,
section 2) with every SDK network call in a worker thread so the voice pipeline never freezes.
`DisabledEnforcer` is the baseline (`DISABLE_ARMORIQ=1`): it allows everything and calls
nothing, and the gateway around it is unchanged, so eval differences come from ArmorIQ alone.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from typing import Any, Literal, Protocol

from armoriq_sdk.session import EnforceResult, ReportOptions
from pydantic import BaseModel

from countersign_agent.bridge.approval import ApprovalBackend, ApprovalOutcome, wait_for_approval
from countersign_agent.contracts import Decision

logger = logging.getLogger("countersign_agent.bridge.enforcer")

# The SDK turns any enforce exception into a block with this reason (session.py:860-864).
SDK_UNAVAILABLE_PREFIX = "enforce-unavailable"


class Verdict(BaseModel):
    decision: Decision
    reason: str | None = None
    policy: str | None = None
    delegation_id: str | None = None
    latency_ms: float = 0.0


class GovernedSession(Protocol):
    """The subset of armoriq_sdk.session.ArmorIQSession the bridge uses (all blocking HTTP)."""

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

    def close(self) -> None: ...


class Enforcer(Protocol):
    mode: Literal["live", "disabled"]
    plan_id: str | None

    async def start(self, user_email: str, goal: str) -> float:
        """Open a session for this identity and declare every tool in one plan. Returns the
        ArmorIQ time in ms. On failure every later check is UNAVAILABLE (fail closed)."""
        ...

    async def check(self, tool: str, arguments: dict[str, Any]) -> Verdict:
        """Never raises: errors become UNAVAILABLE."""
        ...

    async def wait(
        self, delegation_id: str, plan_id: str | None, timeout_s: float
    ) -> ApprovalOutcome:
        """May raise; the caller fails closed."""
        ...

    async def report(
        self, tool: str, arguments: dict[str, Any], result: Any, error: str | None
    ) -> None:
        """Best effort, never raises."""
        ...

    async def close(self) -> None: ...


def _ms_since(started: float) -> float:
    return (time.perf_counter() - started) * 1000


def to_verdict(result: EnforceResult, latency_ms: float) -> Verdict:
    """Only an explicit allow runs a tool; a hold needs a delegation to be approvable."""
    reason = result.reason
    if result.allowed:
        decision = Decision.ALLOW
    elif result.action == "hold":
        if result.delegation_id:
            decision = Decision.HOLD
        else:
            # The SDK still says hold when creating the delegation failed: nobody can approve.
            decision, reason = Decision.UNAVAILABLE, "hold_without_delegation"
    elif (reason or "").startswith(SDK_UNAVAILABLE_PREFIX):
        decision, reason = Decision.UNAVAILABLE, "enforce_unavailable"
    else:
        decision = Decision.BLOCK
    return Verdict(
        decision=decision,
        reason=reason,
        policy=result.matched_policy,
        delegation_id=result.delegation_id if decision is Decision.HOLD else None,
        latency_ms=latency_ms,
    )


class ArmorIQEnforcer:
    mode: Literal["live", "disabled"] = "live"

    def __init__(
        self,
        *,
        session_factory: Callable[[str], GovernedSession],  # blocking; run in a thread
        approvals: ApprovalBackend,
        tool_names: list[str],
        poll_seconds: float,
    ) -> None:
        self._session_factory = session_factory
        self._approvals = approvals
        self._tool_names = tool_names
        self._poll_seconds = poll_seconds
        self._session: GovernedSession | None = None
        self._user_email: str | None = None
        self.plan_id: str | None = None

    async def start(self, user_email: str, goal: str) -> float:
        old, self._session, self.plan_id = self._session, None, None
        if old is not None:
            await self._close_session(old)
        self._user_email = user_email
        started = time.perf_counter()
        session: GovernedSession | None = None
        try:
            session = await asyncio.to_thread(self._session_factory, user_email)
            # Every tool, declared once with no arguments: the plan names what the agent may
            # try this call; the per-call arguments are judged by check().
            token = await asyncio.to_thread(
                session.start_plan, [{"name": n, "args": {}} for n in self._tool_names], goal
            )
        except Exception:
            logger.exception("ArmorIQ session/plan failed; every check will fail closed")
            if session is not None:
                await self._close_session(session)  # stop its observability thread
            return _ms_since(started)
        self._session = session
        self.plan_id = getattr(token, "plan_id", None)
        return _ms_since(started)

    async def check(self, tool: str, arguments: dict[str, Any]) -> Verdict:
        if self._session is None:
            return Verdict(decision=Decision.UNAVAILABLE, reason="no_plan")
        started = time.perf_counter()
        try:
            result = await asyncio.to_thread(self._session.check, tool, arguments, self._user_email)
        except Exception:
            logger.exception("ArmorIQ check failed for %s (fail closed)", tool)
            return Verdict(
                decision=Decision.UNAVAILABLE,
                reason="enforce_error",
                latency_ms=_ms_since(started),
            )
        verdict = to_verdict(result, _ms_since(started))
        if verdict.decision is Decision.UNAVAILABLE:
            logger.warning("ArmorIQ unavailable for %s: %s", tool, result.reason)
        return verdict

    async def wait(
        self, delegation_id: str, plan_id: str | None, timeout_s: float
    ) -> ApprovalOutcome:
        return await wait_for_approval(
            self._approvals,
            delegation_id,
            user_email=self._user_email or "",
            plan_id=plan_id,
            timeout_seconds=timeout_s,
            interval=self._poll_seconds,
        )

    async def report(
        self, tool: str, arguments: dict[str, Any], result: Any, error: str | None
    ) -> None:
        """Like Strands: the tool already ran, so a failed audit must never turn a completed
        action (an issued refund) into an apparent failure."""
        if self._session is None:
            return
        opts = (
            ReportOptions(status="error", error_message=error)
            if error is not None
            else ReportOptions(status="success")
        )
        try:
            await asyncio.to_thread(self._session.report, tool, arguments, result, opts)
        except Exception:
            logger.warning("execution report failed for %s", tool, exc_info=True)

    async def close(self) -> None:
        if self._session is not None:
            await self._close_session(self._session)
            self._session = None

    async def _close_session(self, session: GovernedSession) -> None:
        # Flushes the SDK's observability thread. Documented as never throwing, but a failure
        # here must not turn a finished verify (or a hang-up) into a crash.
        try:
            await asyncio.to_thread(session.close)
        except Exception:
            logger.warning("ArmorIQ session close failed", exc_info=True)


class DisabledEnforcer:
    """Baseline mode: no ArmorIQ calls, every tool is allowed."""

    mode: Literal["live", "disabled"] = "disabled"
    plan_id: str | None = None

    async def start(self, user_email: str, goal: str) -> float:
        return 0.0

    async def check(self, tool: str, arguments: dict[str, Any]) -> Verdict:
        return Verdict(decision=Decision.ALLOW, reason="armoriq_disabled")

    async def wait(
        self, delegation_id: str, plan_id: str | None, timeout_s: float
    ) -> ApprovalOutcome:
        raise RuntimeError("baseline mode never holds a call")

    async def report(
        self, tool: str, arguments: dict[str, Any], result: Any, error: str | None
    ) -> None:
        return None

    async def close(self) -> None:
        return None


class UnavailableEnforcer(DisabledEnforcer):
    """ArmorIQ could not even be reached to build a client: the call goes ahead, and every
    tool fails closed (UNAVAILABLE) instead of the phone call crashing."""

    mode: Literal["live", "disabled"] = "live"

    async def check(self, tool: str, arguments: dict[str, Any]) -> Verdict:
        return Verdict(decision=Decision.UNAVAILABLE, reason="armoriq_unreachable")

    async def wait(
        self, delegation_id: str, plan_id: str | None, timeout_s: float
    ) -> ApprovalOutcome:
        raise RuntimeError("ArmorIQ unreachable: nothing can be approved")
