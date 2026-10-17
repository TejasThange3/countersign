"""The governed tool gateway: the only path from the LLM to hotel-mcp.

For each tool call: inject identity -> ArmorIQ check -> run (allow) / park (hold) / refuse
(block, unavailable) -> report. Identity is the bridge's: it starts unverified, switches to the
verified guest after a successful verify_guest (one new ArmorIQ session and plan), and the
model's `guest_id` is always overwritten (product rules 1-3).
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Literal

from pydantic import BaseModel

from countersign_agent.bridge.enforcer import Enforcer, Verdict
from countersign_agent.bridge.executor import ToolExecutor, ToolOutput
from countersign_agent.bridge.identity import CallIdentity, Verify
from countersign_agent.bridge.masking import Masker
from countersign_agent.bridge.tools import IDENTITY_ARG, BridgeTool
from countersign_agent.contracts import (
    Decision,
    EventSink,
    GatewayEvent,
    Outcome,
    ToolResult,
    ToolSpec,
)

logger = logging.getLogger("countersign_agent.bridge.gateway")

VERIFY_TOOL = "verify_guest"
EventKind = Literal[
    "identity_changed", "tool_requested", "tool_decided", "hold_resolved", "tool_finished"
]

# What the LLM hears. Short and neutral: never a policy name, rule or threshold it could use
# to probe the rules. The detail goes to `reason` and the events.
SAY_BLOCKED = "I can't do that."
SAY_HELD = "That needs a manager's approval. One moment."
SAY_UNAVAILABLE = "I can't do that right now."
SAY_REJECTED = "The manager didn't approve that."
SAY_TIMEOUT = "I couldn't get a manager's approval in time."
SAY_NOT_VERIFIED = "I need to verify who you are first."
SAY_LOCKED_OUT = "I can't verify that right now."
SAY_OTHER_GUEST = "I can't switch to a different booking on this call."
SAY_HOLD_PENDING = "One moment, I'm still waiting on a manager."
SAY_TOOL_FAILED = "Something went wrong with that. Please try again."

# Bridge refusals (reason codes; the decision is BLOCK, made by the bridge, not ArmorIQ).
R_LOCKED_OUT = "verify_locked_out"
R_NOT_VERIFIED = "not_verified"
R_UNKNOWN_TOOL = "unknown_tool"
R_HOLD_PENDING = "hold_pending"
R_OTHER_GUEST = "other_guest"
R_CLOSED = "call_closed"


class _Pending(BaseModel):
    """A held call, parked until wait() resolves it."""

    tool: str
    arguments: dict[str, Any]
    delegation_id: str
    plan_id: str | None
    policy: str | None
    reason: str | None
    latency_ms: float


def content_for(data: Any) -> str:
    return data if isinstance(data, str) else json.dumps(data, default=str)


class GovernedGateway:
    """One per phone call. Implements contracts.ToolGateway."""

    def __init__(
        self,
        call_id: str,
        *,
        tools: dict[str, BridgeTool],
        enforcer: Enforcer,
        executor: ToolExecutor,
        identity: CallIdentity,
        identities: dict[Literal["unverified", "guest"], str],
        masker: Masker,
        events: EventSink | None = None,
    ) -> None:
        self.call_id = call_id
        self._tools = tools
        self._enforcer = enforcer
        self._executor = executor
        self._identity = identity
        self._identities = identities
        self._masker = masker
        self._events = events
        self._pending: dict[str, _Pending] = {}
        # Holds someone is already waiting on. The hold stays in _pending meanwhile (so verify
        # is still refused under it), but a second wait must not run the tool a second time.
        self._waiting: set[str] = set()
        # Tasks inside wait(): close() cancels them so no approval is consumed after hang-up.
        self._wait_tasks: set[asyncio.Task[Any]] = set()
        self._closed = False
        # Serialises identity changes against checks: a check never runs half-way through a
        # re-plan, and the injected guest_id always matches the ArmorIQ identity.
        self._identity_lock = asyncio.Lock()
        # The call-start plan is ArmorIQ overhead too; it is billed to the first tool call.
        self._unbilled_ms = 0.0

    @property
    def mode(self) -> Literal["live", "disabled"]:
        return self._enforcer.mode

    async def start(self) -> None:
        # The guest's plan is minted alongside (it takes seconds) and only takes effect when
        # verify_guest passes.
        self._unbilled_ms = await self._enforcer.start(
            self._identities["unverified"],
            f"Countersign front desk call {self.call_id}",
            then_prepare=(
                self._identities["guest"],
                f"Countersign front desk call {self.call_id}, verified guest",
            ),
        )

    def tool_specs(self) -> list[ToolSpec]:
        return [t.spec for t in self._tools.values()]

    # --- call ---

    async def call(self, name: str, arguments: dict[str, Any]) -> ToolResult:
        tool = self._tools.get(name)
        if tool is None:
            # Not offered, so not in the plan either: the SDK would block it locally.
            await self._emit("tool_requested", {"tool": name, "arguments": arguments})
            return await self._refuse(name, R_UNKNOWN_TOOL, SAY_BLOCKED)
        if self._closed:
            return await self._refuse(name, R_CLOSED, SAY_UNAVAILABLE)
        if name == VERIFY_TOOL:
            return await self._verify(arguments)

        # Check, run and report all happen under the identity the check ran as: a concurrent
        # verify_guest waits for in-flight tools, and sees any hold registered here.
        async with self._identity_lock:
            if self._closed:  # hung up while this call waited for the lock
                return await self._refuse(name, R_CLOSED, SAY_UNAVAILABLE)
            args = self._with_identity(tool, arguments)
            await self._emit("tool_requested", {"tool": name, "arguments": args})
            verdict = await self._enforcer.check(name, args)
            plan_id = self._enforcer.plan_id
            verdict.latency_ms += self._take_unbilled()
            unverified_guest_call = tool.needs_guest_id and not self._identity.verified
            if (
                verdict.decision is Decision.HOLD
                and verdict.delegation_id
                and not unverified_guest_call
            ):
                self._pending[verdict.delegation_id] = _Pending(
                    tool=name,
                    arguments=args,
                    delegation_id=verdict.delegation_id,
                    plan_id=plan_id,
                    policy=verdict.policy,
                    reason=verdict.reason,
                    latency_ms=verdict.latency_ms,
                )
            try:
                await self._emit_decided(name, verdict, plan_id)
            except asyncio.CancelledError:
                # Hung up before the hold reached the agent: nobody can wait on it, and a
                # stale entry would refuse every later verify_guest.
                self._pending.pop(verdict.delegation_id or "", None)
                raise

            if verdict.decision in (Decision.ALLOW, Decision.HOLD) and unverified_guest_call:
                # ArmorIQ was asked first (its block is the audit trail); the bridge still never
                # runs a guest-scoped tool without a verified guest.
                return await self._refuse(name, R_NOT_VERIFIED, SAY_NOT_VERIFIED, verdict, plan_id)
            if verdict.decision is Decision.HOLD and verdict.delegation_id:
                return self._result(
                    name, verdict, Outcome.PENDING, SAY_HELD, plan_id, verdict.delegation_id
                )
            if verdict.decision is not Decision.ALLOW:
                say = SAY_BLOCKED if verdict.decision is Decision.BLOCK else SAY_UNAVAILABLE
                return await self._finish(
                    self._result(name, verdict, Outcome.NOT_RUN, say, plan_id)
                )
            return await self._run(name, args, verdict, plan_id)

    async def _verify(self, arguments: dict[str, Any]) -> ToolResult:
        name = VERIFY_TOOL
        async with self._identity_lock:
            if self._closed:
                return await self._refuse(name, R_CLOSED, SAY_UNAVAILABLE)
            if self._identity.locked_out:
                # The one short-circuit before ArmorIQ: brute-force protection is ours.
                await self._emit("tool_requested", {"tool": name, "arguments": arguments})
                return await self._refuse(name, R_LOCKED_OUT, SAY_LOCKED_OUT)
            args = {k: v for k, v in arguments.items() if k != IDENTITY_ARG}
            await self._emit("tool_requested", {"tool": name, "arguments": args})
            verdict = await self._enforcer.check(name, args)
            plan_id = self._enforcer.plan_id
            verdict.latency_ms += self._take_unbilled()
            await self._emit_decided(name, verdict, plan_id)
            if verdict.decision is not Decision.ALLOW:
                # A held verify_guest is refused too: switching identity would re-plan, and a
                # re-plan drops pending approvals.
                say = SAY_UNAVAILABLE if verdict.decision is Decision.UNAVAILABLE else SAY_BLOCKED
                return await self._finish(
                    self._result(name, verdict, Outcome.NOT_RUN, say, plan_id)
                )
            # Defence in depth: the current policy never holds an unverified caller's tools,
            # but if a policy change ever did, a re-plan here would orphan that approval.
            if self._pending and not self._identity.verified:
                return await self._refuse(name, R_HOLD_PENDING, SAY_HOLD_PENDING, verdict, plan_id)

            output = await self._execute(name, args)
            if output is None or output.is_error:
                return await self._after_run(name, args, verdict, plan_id, output)
            data = output.data if isinstance(output.data, dict) else {}
            outcome = self._identity.record_verify(
                bool(data.get("verified")), data.get(IDENTITY_ARG)
            )
            # Not awaited (~1 s): the caller is waiting to hear whether they're verified.
            await self._enforcer.report(name, args, output.data, None, wait=False)
            if outcome is Verify.SWITCHED:
                verdict.latency_ms += await self._enforcer.start(
                    self._identities["guest"],
                    f"Countersign front desk call {self.call_id} for guest "
                    f"{self._identity.guest_id}",
                )
                await self._emit(
                    "identity_changed",
                    {
                        "from": "unverified",
                        "to": "guest",
                        "guest_id": self._identity.guest_id,
                        "plan_id": self._enforcer.plan_id,
                    },
                )
            if outcome is Verify.OTHER_GUEST:
                # It ran (and was reported), but the other guest's details never reach the LLM.
                result = self._result(name, verdict, Outcome.RAN, SAY_OTHER_GUEST, plan_id)
                result.reason = R_OTHER_GUEST
                return await self._finish(result)
            # The model never sees guest ids: it only ever proposes, the bridge decides whose.
            shown = {k: v for k, v in data.items() if k != IDENTITY_ARG}
            return await self._finish(
                self._result(name, verdict, Outcome.RAN, content_for(shown), plan_id)
            )

    # --- holds ---

    async def wait(self, held: ToolResult, timeout_s: float = 60.0) -> ToolResult:
        # After close() every hold is gone, so this returns unknown_hold.
        pending = None if self._closed else self._pending.get(held.delegation_id or "")
        if pending is not None and pending.delegation_id in self._waiting:
            # Someone is already waiting on this hold; that wait decides it. Not a rejection.
            return held.model_copy(
                update={
                    "outcome": Outcome.NOT_RUN,
                    "reason": "wait_in_progress",
                    "content": SAY_HELD,
                }
            )
        if held.outcome is not Outcome.PENDING or pending is None:
            return held.model_copy(
                update={
                    "outcome": Outcome.NOT_RUN,
                    "reason": "unknown_hold",
                    "content": SAY_BLOCKED,
                }
            )
        # No await between the check above and this claim, so two waits can't both pass.
        self._waiting.add(pending.delegation_id)
        task = asyncio.current_task()
        if task is not None:
            self._wait_tasks.add(task)
        try:
            return await self._wait_claimed(pending, timeout_s)
        finally:
            self._waiting.discard(pending.delegation_id)
            if task is not None:
                self._wait_tasks.discard(task)

    async def _wait_claimed(self, pending: _Pending, timeout_s: float) -> ToolResult:
        verdict = Verdict(
            decision=Decision.HOLD,
            reason=pending.reason,
            policy=pending.policy,
            delegation_id=pending.delegation_id,
            latency_ms=pending.latency_ms,
        )
        hold_data = {
            "tool": pending.tool,
            "delegation_id": pending.delegation_id,
            "plan_id": pending.plan_id,
        }
        try:
            approval = await self._enforcer.wait(pending.delegation_id, pending.plan_id, timeout_s)
        except asyncio.CancelledError:
            # Caller hung up: polling stops and the tool never runs.
            self._pending.pop(pending.delegation_id, None)
            await self._emit("hold_resolved", {**hold_data, "resolution": "cancelled"})
            raise
        except Exception:
            logger.exception("approval wait failed for %s (fail closed)", pending.tool)
            self._pending.pop(pending.delegation_id, None)
            await self._emit("hold_resolved", {**hold_data, "resolution": "error"})
            verdict.decision, verdict.reason = Decision.UNAVAILABLE, "approval_error"
            return await self._finish(
                self._result(
                    pending.tool,
                    verdict,
                    Outcome.NOT_RUN,
                    SAY_UNAVAILABLE,
                    pending.plan_id,
                    pending.delegation_id,
                )
            )
        if approval == "approved":
            # The approval is spent now: close() must not cancel the run half-way (a refund
            # written but never reported), so this wait leaves the cancellable set.
            current = asyncio.current_task()
            if current is not None:
                self._wait_tasks.discard(current)
            # The hold leaves _pending only once the lock is held, so no verify_guest can
            # re-plan between the approval and the run, and the run is reported through the
            # session that asked for it.
            try:
                await self._identity_lock.acquire()
            except asyncio.CancelledError:
                # Hung up while another tool held the lock: the approved tool never runs, and
                # a later wait() can't run it either.
                self._pending.pop(pending.delegation_id, None)
                await self._emit("hold_resolved", {**hold_data, "resolution": "cancelled"})
                raise
            try:
                self._pending.pop(pending.delegation_id, None)
                if self._closed:
                    await self._emit("hold_resolved", {**hold_data, "resolution": "cancelled"})
                    verdict.decision, verdict.reason = Decision.BLOCK, R_CLOSED
                    return await self._finish(
                        self._result(
                            pending.tool,
                            verdict,
                            Outcome.NOT_RUN,
                            SAY_UNAVAILABLE,
                            pending.plan_id,
                            pending.delegation_id,
                        )
                    )
                await self._emit("hold_resolved", {**hold_data, "resolution": approval})
                verdict.reason = "approved"
                return await self._run(
                    pending.tool,
                    pending.arguments,
                    verdict,
                    pending.plan_id,
                    pending.delegation_id,
                )
            finally:
                self._identity_lock.release()
        self._pending.pop(pending.delegation_id, None)
        await self._emit("hold_resolved", {**hold_data, "resolution": approval})
        verdict.reason = approval  # rejected | timeout
        say = SAY_REJECTED if approval == "rejected" else SAY_TIMEOUT
        return await self._finish(
            self._result(
                pending.tool,
                verdict,
                Outcome.NOT_RUN,
                say,
                pending.plan_id,
                pending.delegation_id,
            )
        )

    async def close(self) -> None:
        """Hang-up. Idempotent. Holds are invalidated and waits still polling for a manager
        are cancelled (their callers get CancelledError), so a hung-up call doesn't spend an
        approval. A poll or mark already inside a worker thread can't be stopped, though. A
        tool that is already running, including an approved hold, finishes and is reported
        before the MCP connection and the ArmorIQ session close."""
        if self._closed:
            return
        self._closed = True
        self._pending.clear()
        try:
            others = [t for t in self._wait_tasks if t is not asyncio.current_task()]
            for task in others:
                task.cancel()
            await asyncio.gather(*others, return_exceptions=True)
            async with self._identity_lock:  # in-flight check/run/report finish first
                pass
        finally:
            try:
                await self._executor.close()
            finally:
                await self._enforcer.close()

    # --- helpers ---

    def _with_identity(self, tool: BridgeTool, arguments: dict[str, Any]) -> dict[str, Any]:
        """Drop whatever guest_id the model sent; insert the verified one where the tool takes
        it. `target_guest_id` is a different key and passes through untouched."""
        args = {k: v for k, v in arguments.items() if k != IDENTITY_ARG}
        if tool.needs_guest_id and self._identity.guest_id is not None:
            args[IDENTITY_ARG] = self._identity.guest_id
        return args

    def _take_unbilled(self) -> float:
        ms, self._unbilled_ms = self._unbilled_ms, 0.0
        return ms

    async def _execute(self, name: str, args: dict[str, Any]) -> ToolOutput | None:
        """None means the MCP call itself failed (network, protocol)."""
        try:
            return await self._executor.call_tool(name, args)
        except Exception:
            logger.exception("hotel-mcp call failed for %s", name)
            return None

    async def _run(
        self,
        name: str,
        args: dict[str, Any],
        verdict: Verdict,
        plan_id: str | None,
        delegation_id: str | None = None,
    ) -> ToolResult:
        output = await self._execute(name, args)
        return await self._after_run(name, args, verdict, plan_id, output, delegation_id)

    async def _after_run(
        self,
        name: str,
        args: dict[str, Any],
        verdict: Verdict,
        plan_id: str | None,
        output: ToolOutput | None,
        delegation_id: str | None = None,
    ) -> ToolResult:
        if output is None:
            await self._enforcer.report(name, args, None, "hotel-mcp call failed")
            result = self._result(
                name, verdict, Outcome.ERROR, SAY_TOOL_FAILED, plan_id, delegation_id
            )
        elif output.is_error:
            # Business errors ("booking not found") are for the LLM to explain to the caller.
            text = content_for(output.data)
            await self._enforcer.report(name, args, text, text)
            result = self._result(name, verdict, Outcome.ERROR, text, plan_id, delegation_id)
        else:
            await self._enforcer.report(name, args, output.data, None)
            result = self._result(
                name, verdict, Outcome.RAN, content_for(output.data), plan_id, delegation_id
            )
        return await self._finish(result)

    async def _refuse(
        self,
        name: str,
        reason: str,
        say: str,
        verdict: Verdict | None = None,
        plan_id: str | None = None,
    ) -> ToolResult:
        """A bridge refusal: BLOCK by the bridge, nothing runs. Keeps any ArmorIQ latency."""
        refusal = Verdict(
            decision=Decision.BLOCK,
            reason=reason,
            latency_ms=verdict.latency_ms if verdict else 0.0,
        )
        await self._emit_decided(name, refusal, plan_id, by="bridge")
        return await self._finish(self._result(name, refusal, Outcome.NOT_RUN, say, plan_id))

    def _result(
        self,
        name: str,
        verdict: Verdict,
        outcome: Outcome,
        content: str,
        plan_id: str | None,
        delegation_id: str | None = None,
    ) -> ToolResult:
        return ToolResult(
            tool=name,
            decision=verdict.decision,
            outcome=outcome,
            content=content,
            reason=verdict.reason,
            policy=verdict.policy,
            plan_id=plan_id,
            delegation_id=delegation_id,
            armoriq_mode=self.mode,
            latency_ms=round(verdict.latency_ms, 1),
        )

    async def _finish(self, result: ToolResult) -> ToolResult:
        await self._emit(
            "tool_finished",
            {
                "tool": result.tool,
                "decision": result.decision,
                "outcome": result.outcome,
                "reason": result.reason,
                "content": result.content,
                "plan_id": result.plan_id,
                "delegation_id": result.delegation_id,
                "latency_ms": result.latency_ms,
            },
        )
        return result

    async def _emit_decided(
        self,
        name: str,
        verdict: Verdict,
        plan_id: str | None,
        by: Literal["armoriq", "bridge"] = "armoriq",
    ) -> None:
        await self._emit(
            "tool_decided",
            {
                "tool": name,
                "decision": verdict.decision,
                "reason": verdict.reason,
                "policy": verdict.policy,
                "plan_id": plan_id,
                "delegation_id": verdict.delegation_id,
                "latency_ms": round(verdict.latency_ms, 1),
                "by": by if self.mode == "live" or by == "bridge" else "disabled",
            },
        )

    async def _emit(self, kind: EventKind, data: dict[str, Any]) -> None:
        if self._events is None:
            return
        event = GatewayEvent(
            call_id=self.call_id,
            kind=kind,
            data={"armoriq_mode": self.mode, **self._masker.clean(data)},
        )
        try:
            await self._events(event)
        except Exception:
            # A broken dashboard feed must not change what happens on the phone call.
            logger.warning("event sink failed for %s", kind, exc_info=True)
