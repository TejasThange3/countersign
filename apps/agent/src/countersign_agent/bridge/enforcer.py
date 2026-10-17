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
from concurrent.futures import Executor, ThreadPoolExecutor
from typing import Any, Literal, Protocol

from armoriq_sdk.session import EnforceResult, ReportOptions
from pydantic import BaseModel

from countersign_agent.bridge.approval import ApprovalBackend, ApprovalOutcome, wait_for_approval
from countersign_agent.contracts import Decision

logger = logging.getLogger("countersign_agent.bridge.enforcer")

# The SDK mints a plan's token from `user_email_override`, one field on the shared client
# that every `for_user(...).start_session()` overwrites (client.py:593-601, :1795-1823). Two
# calls opening plans at once on one client could mint a token for the other caller's
# identity, so with a shared client "open session + start plan" runs as one step on this
# single process-wide thread. A dedicated thread (not a lock inside the shared pool) so calls
# queued behind a slow plan never tie up the workers every other call's checks use.
# The gateway factory gives each identity its own client instead (the override then never
# changes), so it passes `plan_executor=None` and plans for different calls mint in parallel.
PLAN_EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="armoriq-plan")


class _PlanFailed(Exception):
    """start_plan failed after the session was built; the session still needs closing."""

    def __init__(self, session: GovernedSession) -> None:
        super().__init__("ArmorIQ plan failed")
        self.session = session


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

    async def start(
        self, user_email: str, goal: str, *, then_prepare: tuple[str, str] | None = None
    ) -> float:
        """Open a session for this identity and declare every tool in one plan. Returns the
        ArmorIQ time in ms. On failure every later check is UNAVAILABLE (fail closed).
        `then_prepare` (email, goal) also starts opening the plan of the identity this call
        may switch to; it saves time only and grants nothing until a start() switches to it."""
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
        self,
        tool: str,
        arguments: dict[str, Any],
        result: Any,
        error: str | None,
        *,
        wait: bool = True,
    ) -> None:
        """Best effort, never raises. `wait=False` sends it in the background, through the
        session that is current now."""
        ...

    async def close(self) -> None: ...


def _ms_since(started: float) -> float:
    return (time.perf_counter() - started) * 1000


def to_verdict(result: EnforceResult, latency_ms: float) -> Verdict:
    """Only an explicit allow runs a tool; a hold needs a delegation to be approvable."""
    reason = result.reason
    if result.allowed and result.delegation_id:
        # The SDK reusing an earlier approval inside check() (session.py:1218-1251). Its lookup
        # matches tool + amount + plan, not the arguments, and it marks the approval used
        # without checking the answer. So a second $250 refund for another booking could spend
        # the approval a pending wait() owns. Approvals are spent only through wait(), with
        # the arguments that were held.
        decision, reason = Decision.UNAVAILABLE, "approval_reused"
    elif result.allowed:
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
        plan_executor: Executor | None = PLAN_EXECUTOR,
    ) -> None:
        self._session_factory = session_factory
        # None: the loop's default pool (each identity has its own client; see PLAN_EXECUTOR).
        self._plan_executor = plan_executor
        self._approvals = approvals
        self._tool_names = tool_names
        self._poll_seconds = poll_seconds
        self._session: GovernedSession | None = None
        self._user_email: str | None = None
        self.plan_id: str | None = None
        # Minting a plan token takes ArmorIQ about 6-7 s, so the verified guest's plan is
        # opened while the call is still unverified, and verify_guest switches to it at once.
        self._standby: asyncio.Future[tuple[GovernedSession, Any]] | None = None
        self._standby_email: str | None = None
        self._closing: set[asyncio.Task[None]] = set()
        self._reporting: set[asyncio.Task[None]] = set()

    def _open_in_background(
        self, user_email: str, goal: str
    ) -> asyncio.Future[tuple[GovernedSession, Any]]:
        return asyncio.get_running_loop().run_in_executor(
            self._plan_executor, self._open_plan, user_email, goal
        )

    def _prepare(self, user_email: str, goal: str) -> None:
        if self._standby is None:
            self._standby_email = user_email
            self._standby = self._open_in_background(user_email, goal)

    def _take_standby(self, user_email: str) -> asyncio.Future[tuple[GovernedSession, Any]] | None:
        standby, self._standby = self._standby, None
        if standby is not None and self._standby_email != user_email:
            standby.add_done_callback(self._close_orphan)
            return None
        return standby

    async def start(
        self, user_email: str, goal: str, *, then_prepare: tuple[str, str] | None = None
    ) -> float:
        old, self._session, self.plan_id = self._session, None, None
        if old is not None:
            # Off the caller's path: closing flushes spans over HTTP (~0.7 s). Reports still
            # in flight go first, so the old session closes with its audit complete.
            task = asyncio.create_task(self._retire(old, list(self._reporting)))
            self._closing.add(task)
            task.add_done_callback(self._closing.discard)
        self._user_email = user_email
        started = time.perf_counter()
        # A worker thread can't be cancelled: if the caller hangs up meanwhile, the session it
        # eventually returns must still be closed, so the thread's result is kept (shield).
        opening = self._take_standby(user_email) or self._open_in_background(user_email, goal)
        if then_prepare is not None:
            self._prepare(*then_prepare)
        try:
            session, token = await asyncio.shield(opening)
        except asyncio.CancelledError:
            opening.add_done_callback(self._close_orphan)
            raise
        except _PlanFailed as failed:
            logger.exception("ArmorIQ plan failed; every check will fail closed")
            # Closed here, off the plan thread, so the next caller's plan isn't held up.
            await self._close_session(failed.session)
            return _ms_since(started)
        except Exception:
            logger.exception("ArmorIQ session failed; every check will fail closed")
            return _ms_since(started)
        self._session = session
        self.plan_id = getattr(token, "plan_id", None)
        return _ms_since(started)

    def _close_orphan(self, opening: asyncio.Future[tuple[GovernedSession, Any]]) -> None:
        if opening.cancelled():
            return
        error = opening.exception()
        if isinstance(error, _PlanFailed):
            session = error.session
        elif error is not None:
            return
        else:
            session, _ = opening.result()
        # Off the event loop: close() flushes the SDK's observability thread over HTTP.
        asyncio.get_running_loop().run_in_executor(None, self._close_quietly, session)

    @staticmethod
    def _close_quietly(session: GovernedSession) -> None:
        try:
            session.close()
        except Exception:
            logger.warning("ArmorIQ session close failed", exc_info=True)

    def _open_plan(self, user_email: str, goal: str) -> tuple[GovernedSession, Any]:
        """Blocking; runs on the plan thread."""
        session = self._session_factory(user_email)
        try:
            # Every tool, declared once with no arguments: the plan names what the agent may
            # try this call; the per-call arguments are judged by check().
            token = session.start_plan([{"name": n, "args": {}} for n in self._tool_names], goal)
        except Exception as exc:
            raise _PlanFailed(session) from exc
        return session, token

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
        self,
        tool: str,
        arguments: dict[str, Any],
        result: Any,
        error: str | None,
        *,
        wait: bool = True,
    ) -> None:
        """Like Strands: the tool already ran, so a failed audit must never turn a completed
        action (an issued refund) into an apparent failure."""
        session = self._session  # bound now: a background report stays on this session
        if session is None:
            return
        opts = (
            ReportOptions(status="error", error_message=error)
            if error is not None
            else ReportOptions(status="success")
        )
        job = asyncio.create_task(self._send_report(session, tool, arguments, result, opts))
        self._reporting.add(job)
        job.add_done_callback(self._reporting.discard)
        if wait:
            await job

    @staticmethod
    async def _send_report(
        session: GovernedSession,
        tool: str,
        arguments: dict[str, Any],
        result: Any,
        opts: ReportOptions,
    ) -> None:
        try:
            await asyncio.to_thread(session.report, tool, arguments, result, opts)
        except Exception:
            logger.warning("execution report failed for %s", tool, exc_info=True)

    async def _retire(self, session: GovernedSession, reports: list[asyncio.Task[None]]) -> None:
        if reports:
            await asyncio.gather(*reports, return_exceptions=True)
        await self._close_session(session)

    async def close(self) -> None:
        if self._reporting:
            await asyncio.gather(*self._reporting, return_exceptions=True)
        standby, self._standby = self._standby, None
        if standby is not None:  # never switched to (the caller didn't verify)
            standby.add_done_callback(self._close_orphan)
        if self._session is not None:
            await self._close_session(self._session)
            self._session = None
        if self._closing:
            await asyncio.gather(*self._closing, return_exceptions=True)

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

    async def start(
        self, user_email: str, goal: str, *, then_prepare: tuple[str, str] | None = None
    ) -> float:
        return 0.0

    async def check(self, tool: str, arguments: dict[str, Any]) -> Verdict:
        return Verdict(decision=Decision.ALLOW, reason="armoriq_disabled")

    async def wait(
        self, delegation_id: str, plan_id: str | None, timeout_s: float
    ) -> ApprovalOutcome:
        raise RuntimeError("baseline mode never holds a call")

    async def report(
        self,
        tool: str,
        arguments: dict[str, Any],
        result: Any,
        error: str | None,
        *,
        wait: bool = True,
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
