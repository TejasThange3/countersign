"""The parts of one call that audio and text mode share: LLM, context, tools, holds, metrics.

Both modes build the same `CallCore`, so text mode exercises the same LLM and gateway path
as a real phone call; only the transport and the STT/TTS services differ.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from typing import Any

from pipecat.frames.frames import LLMMessagesAppendFrame, LLMRunFrame, TTSSpeakFrame
from pipecat.pipeline.worker import PipelineWorker
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import (
    LLMContextAggregatorPair,
    LLMUserAggregatorParams,
)
from pipecat.services.google.llm import GoogleLLMService
from pipecat.services.groq.llm import GroqLLMService
from pipecat.services.llm_service import LLMService

from countersign_agent.contracts import ToolGateway, ToolResult
from countersign_agent.voice.config import AgentSettings
from countersign_agent.voice.holds import ToolRouter, hold_outcome_message, spoken_hold_outcome
from countersign_agent.voice.llm import FallbackGoogleLLMService, FallbackGroqLLMService
from countersign_agent.voice.metrics import TurnMetricsRecorder
from countersign_agent.voice.prompts import system_prompt
from countersign_agent.voice.tools import build_tools_schema

LLMFactory = Callable[[AgentSettings], LLMService]


def gemini_llm(settings: AgentSettings) -> LLMService:
    return FallbackGoogleLLMService(
        api_key=settings.gemini_api_key,
        settings=GoogleLLMService.Settings(
            model=settings.gemini_model, system_instruction=system_prompt(date.today())
        ),
        fallback_model=settings.gemini_fallback_model,
        rate_limit_retries=settings.gemini_rate_limit_retries,
        backoff_s=settings.gemini_rate_limit_backoff_s,
        first_chunk_timeout_s=settings.gemini_first_chunk_timeout_s,
        last_model_timeout_s=settings.gemini_last_model_timeout_s,
        cooldown_s=settings.gemini_model_cooldown_s,
    )


def groq_llm(settings: AgentSettings) -> LLMService:
    if not settings.groq_api_key:
        raise RuntimeError("GROQ_API_KEY is not set (or set LLM_PROVIDER=gemini)")
    return FallbackGroqLLMService(
        api_key=settings.groq_api_key,
        settings=GroqLLMService.Settings(
            model=settings.llm_model,
            system_instruction=system_prompt(date.today()),
            reasoning_effort=settings.llm_reasoning_effort,
        ),
        fallback_model=settings.llm_fallback_model,
        max_rate_limit_wait_s=settings.llm_rate_limit_max_wait_s,
        cooldown_s=settings.llm_model_cooldown_s,
        request_timeout_s=settings.llm_request_timeout_s,
        busy_message=settings.llm_busy_message,
    )


def make_llm(settings: AgentSettings) -> LLMService:
    """The LLM for one call, from LLM_PROVIDER."""
    return groq_llm(settings) if settings.llm_provider == "groq" else gemini_llm(settings)


class PipelineCallOutput:
    """`CallOutput` that queues frames at the top of a running pipeline.

    Subclasses decide what hold filler is (audio in audio mode, a marker in text mode).
    `worker` is set once the pipeline worker exists.
    """

    def __init__(self) -> None:
        self.worker: PipelineWorker | None = None
        # Turn-taking for late outcomes: a hold decided while the caller is talking must not
        # make the bot talk over them. The outcome goes into the context at once, but the
        # inference that speaks it waits for the caller's turn to end.
        self.caller_speaking = False
        # Outcome messages added during the caller's turn that no inference has seen yet.
        self._unspoken: list[dict[str, str]] = []

    async def say(self, text: str) -> None:
        await self._queue(TTSSpeakFrame(text))

    async def play_filler(self) -> None:
        return None

    async def deliver_hold_outcome(
        self, tool: str, result: ToolResult, *, interrupted: bool = False
    ) -> None:
        message = hold_outcome_message(tool, result, interrupted=interrupted)
        if self.speaks_outcome_directly(interrupted=interrupted):
            # The decision is spoken word for word (see `spoken_hold_outcome`) and recorded
            # in the context as said, so later turns build on the true outcome.
            text = spoken_hold_outcome(tool, result)
            said = {"role": "assistant", "content": text}
            await self._queue(LLMMessagesAppendFrame(messages=[message, said], run_llm=False))
            await self._queue(TTSSpeakFrame(text))
            return
        if self.caller_speaking:
            # Several outcomes during one caller turn coalesce into one inference later.
            self._unspoken.append(message)
            await self._queue(LLMMessagesAppendFrame(messages=[message], run_llm=False))
            return
        # (A turn that has just begun may not have flagged `caller_speaking` yet: Pipecat
        # interrupts first and runs the turn handlers as tasks. Its interruption cancels
        # this reply too, so the window is harmless.)
        await self._queue(LLMMessagesAppendFrame(messages=[message], run_llm=True))

    def speaks_outcome_directly(self, *, interrupted: bool) -> bool:
        """A decided hold is spoken verbatim unless the caller is mid-turn (then the LLM
        answers both at the end of the turn) or the call was interrupted mid-flight."""
        return not interrupted and not self.caller_speaking

    def watch_caller_turns(self, user_aggregator: Any) -> None:
        """Follow the caller's turns from the user context aggregator's events."""

        @user_aggregator.event_handler("on_user_turn_started")
        async def _started(_aggregator: Any, _strategy: Any) -> None:
            self.caller_speaking = True

        @user_aggregator.event_handler("on_user_turn_message_added")
        async def _message_added(aggregator: Any, _message: Any) -> None:
            # The caller's words were just written to the context, and that write runs an
            # inference. It answers the outcomes too, but only those already in the context
            # before the words (the append is queued, so in a race it can land later).
            earlier = aggregator.context.get_messages()[:-1]
            self._unspoken = [m for m in self._unspoken if m not in earlier]

        @user_aggregator.event_handler("on_user_turn_stopped")
        async def _stopped(_aggregator: Any, _strategy: Any, _message: Any) -> None:
            self.caller_speaking = False
            if self._unspoken:
                # No inference has seen these (a wordless turn, or the race above).
                self._unspoken = []
                await self._queue(LLMRunFrame())

    async def _queue(self, frame: TTSSpeakFrame | LLMMessagesAppendFrame | LLMRunFrame) -> None:
        if self.worker is None:
            raise RuntimeError("call output used before the pipeline started")
        await self.worker.queue_frame(frame)


class CallCore:
    def __init__(
        self,
        call_id: str,
        gateway: ToolGateway,
        settings: AgentSettings,
        output: PipelineCallOutput,
        *,
        llm_factory: LLMFactory = make_llm,
        user_params: LLMUserAggregatorParams | None = None,
    ) -> None:
        self.call_id = call_id
        self.gateway = gateway
        self.output = output
        self.tool_results: list[ToolResult] = []
        self.metrics = TurnMetricsRecorder(call_id, turns_from_speech=user_params is not None)
        self.router = ToolRouter(
            gateway,
            output,
            hold_timeout_s=settings.hold_timeout_s,
            filler_start_s=settings.hold_filler_timing()[0],
            filler_interval_s=settings.hold_filler_timing()[1],
            on_result=self._record_result,
        )
        self.llm = llm_factory(settings)
        if isinstance(self.llm, (FallbackGoogleLLMService, FallbackGroqLLMService)):
            self.llm.on_model_used = self.metrics.record_model
        self.context = LLMContext(
            tools=build_tools_schema(gateway.tool_specs(), self.router.handle)
        )
        # Audio mode passes VAD params here; text mode has no audio to detect turns in.
        self.aggregators = LLMContextAggregatorPair(self.context, user_params=user_params)
        output.watch_caller_turns(self.aggregators.user())

    async def close(self) -> None:
        """Hang up: cancel pending holds first so no held tool runs, then close the gateway."""
        await self.router.close()
        await self.gateway.close()
        self.metrics.finish()

    async def _record_result(self, result: ToolResult) -> None:
        self.tool_results.append(result)
