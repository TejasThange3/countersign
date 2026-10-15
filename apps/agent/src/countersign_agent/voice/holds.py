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

    async def deliver_hold_outcome(self, tool: str, result: ToolResult) -> None:
        """Add a held call's final outcome to the context and let the LLM speak it."""
        ...


ResultListener = Callable[[ToolResult], Awaitable[None]]


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
    ) -> None:
        self._gateway = gateway
        self._output = output
        self._hold_timeout_s = hold_timeout_s
        self._filler_interval_s = filler_interval_s
        self._on_result = on_result
        # Tool name -> the background task waiting on that tool's held call.
        self._pending: dict[str, asyncio.Task[None]] = {}
        self._closed = False

    @property
    def pending_tools(self) -> list[str]:
        return list(self._pending)

    def has_pending_holds(self) -> bool:
        return bool(self._pending)

    async def handle(self, params: FunctionCallParams) -> None:
        name = params.function_name
        if name in self._pending:
            logger.info("tool %s called again during its hold; not sent to the gateway", name)
            await params.result_callback(STILL_WAITING_RESULT.format(tool=name))
            return

        result = await self._gateway.call(name, dict(params.arguments))
        await self._notify(result)

        if result.outcome is not Outcome.PENDING:
            await params.result_callback(result.content)
            return

        if self._closed:
            # The call ended while the gateway was deciding; nobody is left to wait for.
            await params.result_callback(PENDING_RESULT)
            return

        self._pending[name] = asyncio.create_task(self._wait(name, result), name=f"hold:{name}")
        await self._output.say(HOLD_ANNOUNCEMENT)
        await params.result_callback(
            PENDING_RESULT, properties=FunctionCallResultProperties(run_llm=False)
        )

    async def wait_for_holds(self) -> None:
        """Block until no hold is pending (used by text mode to return a whole turn)."""
        while self._pending:
            await asyncio.gather(*self._pending.values(), return_exceptions=True)

    async def close(self) -> None:
        """The caller hung up: cancel every pending wait so no held tool runs afterwards."""
        self._closed = True
        tasks = list(self._pending.values())
        for task in tasks:
            task.cancel()
        for task in tasks:
            with contextlib.suppress(asyncio.CancelledError):
                await task
        self._pending.clear()

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
        await self._output.deliver_hold_outcome(name, final)

    async def _await_decision(self, held: ToolResult) -> ToolResult:
        try:
            async with asyncio.timeout(self._hold_timeout_s + WAIT_GRACE_S):
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


def hold_outcome_message(tool: str, result: ToolResult) -> dict[str, str]:
    """The context message that tells the LLM how a held call ended."""
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
