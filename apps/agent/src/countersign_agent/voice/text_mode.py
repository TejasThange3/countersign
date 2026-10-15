"""Text mode: the voice agent with STT and TTS left out.

Typed text goes in as a user message and the reply comes back as text. It runs through the
same Pipecat context aggregators, LLM, tool router and gateway as a phone call, so evals can
drive whole conversations without spending ElevenLabs credits.

    session = await TextSession.open("call-1", factory, settings)
    reply = await session.send("Do you have a room on Nov 2?")
    await session.close()   # hang up; cancels any pending hold
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from pipecat.frames.frames import (
    ErrorFrame,
    Frame,
    FunctionCallResultFrame,
    FunctionCallsStartedFrame,
    LLMFullResponseEndFrame,
    LLMFullResponseStartFrame,
    LLMMessagesAppendFrame,
    LLMTextFrame,
    TTSSpeakFrame,
)
from pipecat.observers.base_observer import BaseObserver, FramePushed
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.worker import PipelineParams, PipelineWorker
from pipecat.processors.frame_processor import FrameDirection
from pipecat.workers.runner import WorkerRunner
from pydantic import BaseModel, Field

from countersign_agent.contracts import GatewayFactory, ToolResult
from countersign_agent.voice.config import AgentSettings
from countersign_agent.voice.metrics import TurnMetrics
from countersign_agent.voice.session import CallCore, LLMFactory, PipelineCallOutput, gemini_llm

logger = logging.getLogger(__name__)


class TextReply(BaseModel):
    """Everything the agent produced since the previous reply, in order."""

    call_id: str
    messages: list[str] = Field(default_factory=list)
    tool_results: list[ToolResult] = Field(default_factory=list)
    pending_holds: list[str] = Field(default_factory=list)
    filler_played: int = 0
    errors: list[str] = Field(default_factory=list)
    metrics: TurnMetrics | None = None
    # Every Gemini model that answered during this reply (more than one means a fallback).
    models: list[str] = Field(default_factory=list)


class _TurnTracker(BaseObserver):
    """Watches the pipeline to collect assistant text and tell when the agent is idle."""

    def __init__(self) -> None:
        super().__init__()
        self.messages: list[str] = []
        self.errors: list[str] = []
        self.filler_played = 0
        self.responding = False
        self.calls_in_flight = 0
        self.awaiting_response = False
        self.changed = asyncio.Event()
        self._buffer: list[str] = []

    async def on_push_frame(self, data: FramePushed) -> None:
        if data.first_push:
            self._observe(data.frame, data.direction)

    def _observe(self, frame: Frame, direction: FrameDirection) -> None:
        if isinstance(frame, ErrorFrame):
            self.errors.append(str(frame.error))
            self.responding = False
            self.awaiting_response = False
        elif direction is not FrameDirection.DOWNSTREAM:
            return
        elif isinstance(frame, LLMFullResponseStartFrame):
            self.responding = True
            self.awaiting_response = False
            self._buffer = []
        elif isinstance(frame, LLMTextFrame):
            self._buffer.append(frame.text)
        elif isinstance(frame, LLMFullResponseEndFrame):
            self._flush()
            self.responding = False
        elif isinstance(frame, TTSSpeakFrame):
            self.messages.append(frame.text)
        elif isinstance(frame, FunctionCallsStartedFrame):
            self.calls_in_flight += len(frame.function_calls)
        elif isinstance(frame, FunctionCallResultFrame):
            self.calls_in_flight = max(0, self.calls_in_flight - 1)
            if _result_runs_llm(frame) and self.calls_in_flight == 0:
                self.awaiting_response = True
        else:
            return
        self.changed.set()

    def _flush(self) -> None:
        text = "".join(self._buffer).strip()
        if text:
            self.messages.append(text)
        self._buffer = []

    @property
    def busy(self) -> bool:
        return self.responding or self.calls_in_flight > 0 or self.awaiting_response


def _result_runs_llm(frame: FunctionCallResultFrame) -> bool:
    """Mirror of the assistant aggregator's rule for running inference after a result."""
    if not frame.result:
        return False
    if frame.properties and frame.properties.run_llm is not None:
        return frame.properties.run_llm
    if frame.run_llm is not None:
        return frame.run_llm
    return True


class _TextCallOutput(PipelineCallOutput):
    def __init__(self) -> None:
        super().__init__()
        self.tracker = _TurnTracker()

    async def play_filler(self) -> None:
        # No audio in text mode; count it so evals can see filler would have played.
        self.tracker.filler_played += 1
        self.tracker.changed.set()

    async def deliver_hold_outcome(
        self, tool: str, result: ToolResult, *, interrupted: bool = False
    ) -> None:
        self.tracker.awaiting_response = True
        await super().deliver_hold_outcome(tool, result, interrupted=interrupted)


class TextSession:
    def __init__(self, core: CallCore, output: _TextCallOutput, settings: AgentSettings) -> None:
        self.core = core
        self.call_id = core.call_id
        self._output = output
        self._tracker = output.tracker
        self._settings = settings
        self._lock = asyncio.Lock()
        self._results_sent = 0
        self._closed = False

        pipeline = Pipeline([core.aggregators.user(), core.llm, core.aggregators.assistant()])
        self._worker = PipelineWorker(
            pipeline,
            params=PipelineParams(enable_metrics=True, enable_usage_metrics=True),
            observers=[self._tracker, core.metrics],
            cancel_on_idle_timeout=False,
            idle_timeout_secs=None,
        )
        output.worker = self._worker
        self._runner = WorkerRunner(handle_sigint=False)
        self._run_task: asyncio.Task[None] | None = None

    @classmethod
    async def open(
        cls,
        call_id: str,
        factory: GatewayFactory,
        settings: AgentSettings,
        *,
        llm_factory: LLMFactory = gemini_llm,
    ) -> TextSession:
        gateway = await factory.open_call(call_id)
        try:
            output = _TextCallOutput()
            core = CallCore(call_id, gateway, settings, output, llm_factory=llm_factory)
        except BaseException:
            await gateway.close()
            raise
        try:
            session = cls(core, output, settings)
        except BaseException:
            await core.close()
            raise
        try:
            await session._start()
        except BaseException:
            # The session was never registered, so nothing else would close it.
            await session.close()
            raise
        return session

    async def _start(self) -> None:
        started = asyncio.Event()

        @self._worker.event_handler("on_pipeline_started")
        async def _on_started(_worker: Any, _frame: Any) -> None:
            started.set()

        await self._runner.add_workers(self._worker)
        self._run_task = asyncio.create_task(self._runner.run(), name=f"text:{self.call_id}")
        await asyncio.wait_for(started.wait(), timeout=10)

    async def send(
        self, text: str, *, wait_for_holds: bool = True, timeout_s: float | None = None
    ) -> TextReply:
        """One caller turn. Returns when the agent has finished responding (and, by
        default, when every hold has been decided and its outcome spoken)."""
        if self._closed:
            raise RuntimeError(f"text call {self.call_id} is closed")
        async with self._lock:
            self.core.metrics.start_turn()
            self._tracker.awaiting_response = True
            await self._worker.queue_frame(
                LLMMessagesAppendFrame(messages=[{"role": "user", "content": text}], run_llm=True)
            )
            return await self._collect(wait_for_holds, timeout_s)

    async def collect(
        self, *, wait_for_holds: bool = True, timeout_s: float | None = None
    ) -> TextReply:
        """Anything said since the last reply without sending a turn, e.g. a hold outcome
        that arrived after `send(..., wait_for_holds=False)` returned."""
        async with self._lock:
            return await self._collect(wait_for_holds, timeout_s)

    async def close(self) -> None:
        """Hang up. Pending holds are cancelled before the gateway closes."""
        if self._closed:
            return
        self._closed = True
        try:
            await self.core.close()
        finally:
            await self._runner.cancel(reason="text call closed")
            if self._run_task is not None:
                await self._run_task

    async def _collect(self, wait_for_holds: bool, timeout_s: float | None) -> TextReply:
        limit = timeout_s if timeout_s is not None else self._settings.hold_timeout_s + 60
        async with asyncio.timeout(limit):
            await self._wait_idle(wait_for_holds)
        return self._drain()

    async def _wait_idle(self, wait_for_holds: bool) -> None:
        while True:
            holds = wait_for_holds and self.core.router.has_pending_holds()
            if not self._tracker.busy and not holds:
                # Frames hop between processors asynchronously; re-check after a beat so a
                # result that is about to trigger the next inference is not missed.
                await asyncio.sleep(0.05)
                holds = wait_for_holds and self.core.router.has_pending_holds()
                if not self._tracker.busy and not holds:
                    return
            self._tracker.changed.clear()
            try:
                async with asyncio.timeout(0.5):
                    await self._tracker.changed.wait()
            except TimeoutError:
                continue

    def _drain(self) -> TextReply:
        tracker = self._tracker
        results = self.core.tool_results[self._results_sent :]
        self._results_sent = len(self.core.tool_results)
        turn = self.core.metrics.current
        reply = TextReply(
            call_id=self.call_id,
            messages=list(tracker.messages),
            tool_results=list(results),
            pending_holds=self.core.router.pending_tools,
            filler_played=tracker.filler_played,
            errors=list(tracker.errors),
            metrics=turn.model_copy(deep=True),
            models=list(turn.models),
        )
        tracker.messages.clear()
        tracker.errors.clear()
        tracker.filler_played = 0
        return reply
