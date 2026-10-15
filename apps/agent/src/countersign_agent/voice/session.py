"""The parts of one call that audio and text mode share: LLM, context, tools, holds, metrics.

Both modes build the same `CallCore`, so text mode exercises the same LLM and gateway path
as a real phone call; only the transport and the STT/TTS services differ.
"""

from __future__ import annotations

from collections.abc import Callable

from pipecat.frames.frames import LLMMessagesAppendFrame, TTSSpeakFrame
from pipecat.pipeline.worker import PipelineWorker
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import (
    LLMContextAggregatorPair,
    LLMUserAggregatorParams,
)
from pipecat.services.google.llm import GoogleLLMService
from pipecat.services.llm_service import LLMService

from countersign_agent.contracts import ToolGateway, ToolResult
from countersign_agent.voice.config import AgentSettings
from countersign_agent.voice.holds import ToolRouter, hold_outcome_message
from countersign_agent.voice.llm import FallbackGoogleLLMService
from countersign_agent.voice.metrics import TurnMetricsRecorder
from countersign_agent.voice.prompts import SYSTEM_PROMPT
from countersign_agent.voice.tools import build_tools_schema

LLMFactory = Callable[[AgentSettings], LLMService]


def gemini_llm(settings: AgentSettings) -> LLMService:
    return FallbackGoogleLLMService(
        api_key=settings.gemini_api_key,
        settings=GoogleLLMService.Settings(
            model=settings.gemini_model, system_instruction=SYSTEM_PROMPT
        ),
        fallback_model=settings.gemini_fallback_model,
        rate_limit_retries=settings.gemini_rate_limit_retries,
        backoff_s=settings.gemini_rate_limit_backoff_s,
        first_chunk_timeout_s=settings.gemini_first_chunk_timeout_s,
        cooldown_s=settings.gemini_model_cooldown_s,
    )


class PipelineCallOutput:
    """`CallOutput` that queues frames at the top of a running pipeline.

    Subclasses decide what hold filler is (audio in audio mode, a marker in text mode).
    `worker` is set once the pipeline worker exists.
    """

    def __init__(self) -> None:
        self.worker: PipelineWorker | None = None

    async def say(self, text: str) -> None:
        await self._queue(TTSSpeakFrame(text))

    async def play_filler(self) -> None:
        return None

    async def deliver_hold_outcome(self, tool: str, result: ToolResult) -> None:
        await self._queue(
            LLMMessagesAppendFrame(messages=[hold_outcome_message(tool, result)], run_llm=True)
        )

    async def _queue(self, frame: TTSSpeakFrame | LLMMessagesAppendFrame) -> None:
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
        llm_factory: LLMFactory = gemini_llm,
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
            filler_interval_s=settings.hold_filler_interval_s,
            on_result=self._record_result,
        )
        self.llm = llm_factory(settings)
        if isinstance(self.llm, FallbackGoogleLLMService):
            self.llm.on_model_used = self.metrics.record_model
        self.context = LLMContext(
            tools=build_tools_schema(gateway.tool_specs(), self.router.handle)
        )
        # Audio mode passes VAD params here; text mode has no audio to detect turns in.
        self.aggregators = LLMContextAggregatorPair(self.context, user_params=user_params)

    async def close(self) -> None:
        """Hang up: cancel pending holds first so no held tool runs, then close the gateway."""
        await self.router.close()
        await self.gateway.close()
        self.metrics.finish()

    async def _record_result(self, result: ToolResult) -> None:
        self.tool_results.append(result)
