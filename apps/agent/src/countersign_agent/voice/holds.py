"""Routes every LLM tool call through the gateway and handles held calls.

A held call must never block the voice pipeline. The flow for one hold:

1. `gateway.call()` returns quickly with outcome PENDING.
2. The caller hears a fixed line right away ("That needs a manager's approval...").
3. The LLM gets a "pending" function result with `run_llm=False`, so it does not talk over
   that line.
4. A background task plays cached filler and awaits `gateway.wait()`.
5. When the wait ends (approved, rejected or timed out), the outcome is added to the context
   and the LLM speaks it.

While a hold is pending, another call to the same tool (any arguments) is answered with
"still waiting" and never reaches the gateway. The key is the tool name rather than the
exact arguments, because the LLM may phrase the same request differently (250 vs 250.0).
Hanging up cancels every pending wait, so a held tool never runs after the call ends.

A caller talking over the bot (barge-in) does not cancel an acting tool call. Pipecat cancels
the handler, but the gateway call keeps running in a router-owned task and its outcome is
added to the context afterwards, so a refund that already committed is never lost and asked
for again. Only hanging up (`close()`) cancels it.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from collections.abc import Awaitable, Callable
from typing import Protocol

from pipecat.frames.frames import FunctionCallResultProperties
from pipecat.services.llm_service import FunctionCallParams

from countersign_agent.contracts import Outcome, ToolGateway, ToolResult

logger = logging.getLogger(__name__)

HOLD_ANNOUNCEMENT = "That needs a manager's approval. One moment while I check."

# Function result the LLM sees for the original call while the hold is pending.
PENDING_RESULT = (
    "PENDING: this request is waiting for a manager's approval. The caller has already been "
    "told to hold. Do not call this tool again; the outcome will be given to you when it is "
    "decided."
)

# Function result for a repeat call to a tool whose earlier call is still held.
STILL_WAITING_RESULT = (
    "STILL_WAITING: an earlier {tool} request is still waiting for a manager's approval. This "
    "call was not run. Briefly acknowledge the caller, tell them you are still waiting on the "
    "approval, and do not call {tool} again."
)

# Function result for a second concurrent call to the same tool in one LLM response.
DUPLICATE_RESULT = (
    "DUPLICATE: {tool} was requested twice at the same time. Only the first request was "
    "processed; this one was not run."
)

# Function result when the gateway itself failed. Says nothing about why, by design.
GATEWAY_ERROR_RESULT = "ERROR: that could not be done right now, so nothing was changed."

# Function result for a call that arrives after the caller hung up.
CALL_ENDED_RESULT = "CALL_ENDED: the call has ended, so this was not run."

# Seconds allowed past the gateway's own timeout before we give up on a misbehaving wait.
WAIT_GRACE_S = 10.0


class CallOutput(Protocol):
    """How the router talks back to the caller. Audio and text mode implement it differently."""

    async def say(self, text: str) -> None:
        """Speak a fixed line now (TTS in audio mode, a transcript line in text mode)."""
        ...

    async def play_filler(self) -> None:
        """Play one short piece of pre-made hold filler. Must not spend TTS credits."""
        ...

    async def deliver_hold_outcome(
        self, tool: str, result: ToolResult, *, interrupted: bool = False
    ) -> None:
        """Add a call's late outcome to the context and let the LLM speak it: a held call
        that was decided, or (`interrupted`) a call whose handler a barge-in cancelled."""
        ...


ResultListener = Callable[[ToolResult], Awaitable[None]]


class _Delivery:
    """Whether the function call's handler is still there to take the result."""

    abandoned = False


class ToolRouter:
    """One per phone call. Pipecat calls `handle` for every tool call the LLM makes."""

    def __init__(
        self,
        gateway: ToolGateway,
        output: CallOutput,
        *,
        hold_timeout_s: float,
        filler_interval_s: float,
        on_result: ResultListener | None = None,
        wait_grace_s: float = WAIT_GRACE_S,
    ) -> None:
        self._gateway = gateway
        self._output = output
        self._hold_timeout_s = hold_timeout_s
        self._filler_interval_s = filler_interval_s
        self._on_result = on_result
        # Tool name -> the background task waiting on that tool's held call.
        self._pending: dict[str, asyncio.Task[None]] = {}
        # Tool names whose gateway.call is running right now.
        self._in_flight: set[str] = set()
        # Tool name -> the task running an acting tool's call (it outlives a barge-in).
        self._acting: dict[str, asyncio.Task[None]] = {}
        self._side_effect_tools = {s.name for s in gateway.tool_specs() if s.tier != "read"}
        self._wait_grace_s = wait_grace_s
        self._closed = False

    @property
    def pending_tools(self) -> list[str]:
        return list(self._pending)

    def has_pending_holds(self) -> bool:
        return bool(self._pending or self._acting)

    async def handle(self, params: FunctionCallParams) -> None:
        name = params.function_name
        if self._closed:
            # Hangup has begun: a handler that was already queued must not start an action
            # that close() will never see.
            logger.warning("tool %s requested after hangup; not sent to the gateway", name)
            await params.result_callback(CALL_ENDED_RESULT)
            return
        if name in self._pending:
            logger.info("tool %s called again during its hold; not sent to the gateway", name)
            await params.result_callback(STILL_WAITING_RESULT.format(tool=name))
            return
        if name in self._in_flight and name in self._side_effect_tools:
            # The LLM asked for the same acting tool twice in one response (handlers run
            # concurrently). Only the first may reach the gateway: two refunds are two refunds.
            # Reads are exempt; two availability checks for different dates are fine.
            logger.warning("tool %s requested twice at once; second call not sent", name)
            await params.result_callback(DUPLICATE_RESULT.format(tool=name))
            return

        self._in_flight.add(name)
        if name not in self._side_effect_tools:
            # Reads change nothing, so a barge-in may simply cancel them.
            await self._run(name, params, _Delivery())
            return

        delivery = _Delivery()
        task = asyncio.create_task(self._run(name, params, delivery), name=f"call:{name}")
        self._acting[name] = task
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            if not task.done():
                # Barge-in (or hangup, which `close()` handles by cancelling the task).
                delivery.abandoned = True
                logger.info("handler for %s cancelled; the call finishes in the background", name)
            raise

    async def _run(self, name: str, params: FunctionCallParams, delivery: _Delivery) -> None:
        try:
            try:
                result = await self._gateway.call(name, dict(params.arguments))
            except Exception:
                # Fail closed, and still settle the function call so the LLM isn't left
                # waiting on a result that never comes.
                logger.exception("gateway.call failed for %s; treating as not done", name)
                if not delivery.abandoned:
                    await params.result_callback(GATEWAY_ERROR_RESULT)
                return
            await self._notify(result)

            if result.outcome is not Outcome.PENDING:
                if not delivery.abandoned:
                    await params.result_callback(result.content)
                elif not self._closed:
                    await self._output.deliver_hold_outcome(name, result, interrupted=True)
                return

            if self._closed:
                # The call ended while the gateway was deciding; nobody is left to wait for.
                if not delivery.abandoned:
                    await params.result_callback(PENDING_RESULT)
                return

            task = asyncio.create_task(self._wait(name, result), name=f"hold:{name}")
            self._pending[name] = task
        finally:
            self._in_flight.discard(name)
            self._acting.pop(name, None)
        await self._output.say(HOLD_ANNOUNCEMENT)
        if not delivery.abandoned:
            await params.result_callback(
                PENDING_RESULT, properties=FunctionCallResultProperties(run_llm=False)
            )

    async def wait_for_holds(self) -> None:
        """Block until no hold is pending (used by text mode to return a whole turn)."""
        while self._pending or self._acting:
            tasks = [*self._pending.values(), *self._acting.values()]
            await asyncio.gather(*tasks, return_exceptions=True)

    async def close(self) -> None:
        """The caller hung up: cancel every pending wait so no held tool runs afterwards."""
        self._closed = True
        tasks = [*self._acting.values(), *self._pending.values()]
        for task in tasks:
            task.cancel()
        for task in tasks:
            with contextlib.suppress(asyncio.CancelledError):
                await task
        # An acting call cancelled mid-flight may have started a hold before it stopped.
        for task in list(self._pending.values()):
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        self._pending.clear()
        self._acting.clear()

    async def _wait(self, name: str, held: ToolResult) -> None:
        filler = asyncio.create_task(self._filler_loop(), name=f"hold-filler:{name}")
        try:
            final = await self._await_decision(held)
        finally:
            filler.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await filler
            self._pending.pop(name, None)
        await self._notify(final)
        if self._closed:
            # Hung up between the decision and delivery: nobody is left to tell.
            return
        await self._output.deliver_hold_outcome(name, final)

    async def _await_decision(self, held: ToolResult) -> ToolResult:
        try:
            async with asyncio.timeout(self._hold_timeout_s + self._wait_grace_s):
                return await self._gateway.wait(held, timeout_s=self._hold_timeout_s)
        except TimeoutError:
            logger.error("gateway.wait overran its timeout for %s; treating as refusal", held.tool)
            return _refused(held, "hold_wait_overrun")
        except Exception:
            # Fail closed: an error while waiting must never look like an approval.
            logger.exception("gateway.wait failed for %s; treating as refusal", held.tool)
            return _refused(held, "hold_wait_error")

    async def _filler_loop(self) -> None:
        while True:
            await asyncio.sleep(self._filler_interval_s)
            await self._output.play_filler()

    async def _notify(self, result: ToolResult) -> None:
        if self._on_result is not None:
            await self._on_result(result)


def _refused(held: ToolResult, reason: str) -> ToolResult:
    return held.model_copy(
        update={
            "outcome": Outcome.NOT_RUN,
            "content": "The manager's approval could not be obtained, so this was not done.",
            "reason": reason,
        }
    )


def hold_outcome_message(
    tool: str, result: ToolResult, *, interrupted: bool = False
) -> dict[str, str]:
    """The context message that tells the LLM how a held (or interrupted) call ended."""
    if interrupted:
        return {
            "role": "developer",
            "content": (
                f"The earlier {tool} call was still running when the caller spoke, and it has "
                f"now finished with outcome {result.outcome.value}. Tool result: "
                f"{json.dumps(result.content)}. It has already been processed, so do not "
                f"call {tool} again for it. Tell the caller the outcome briefly."
            ),
        }
    if result.outcome is Outcome.RAN:
        status = "APPROVED and completed"
    elif result.outcome is Outcome.ERROR:
        status = "approved, but the action itself FAILED"
    else:
        status = "NOT approved, so nothing was done"
    return {
        "role": "developer",
        "content": (
            f"Update on the earlier {tool} request that was waiting for a manager: it was "
            f"{status}. Tool result: {json.dumps(result.content)}. Tell the caller the outcome "
            "now, in one or two sentences."
        ),
    }
