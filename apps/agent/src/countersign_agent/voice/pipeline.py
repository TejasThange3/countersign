"""The audio pipeline for one phone call.

    transport in -> STT -> user context (Silero VAD + smart-turn) -> LLM (tools)
                 -> ElevenLabs TTS -> transport out -> assistant context

Barge-in: the user aggregator's VAD start strategy interrupts the bot when the caller talks
over it, which clears queued TTS audio and cancels a running LLM response.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from pipecat.frames.frames import OutputAudioRawFrame
from pipecat.observers.user_bot_latency_observer import UserBotLatencyObserver
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.worker import PipelineParams, PipelineWorker
from pipecat.processors.aggregators.llm_response_universal import (
    LLMUserAggregatorParams,
)
from pipecat.services.elevenlabs.tts import ElevenLabsTTSService
from pipecat.services.stt_service import STTService
from pipecat.transports.base_transport import BaseTransport
from pipecat.workers.runner import WorkerRunner

from countersign_agent.contracts import GatewayFactory
from countersign_agent.voice.config import AgentSettings
from countersign_agent.voice.filler import SAMPLE_RATE, load_filler
from countersign_agent.voice.recording import InboundAudioRecorder
from countersign_agent.voice.session import CallCore, PipelineCallOutput
from countersign_agent.voice.vad import make_vad

logger = logging.getLogger(__name__)


class AudioCallOutput(PipelineCallOutput):
    """Speaks through TTS and plays the cached filler audio straight to the transport."""

    def __init__(self, filler: bytes) -> None:
        super().__init__()
        self._filler = filler

    async def play_filler(self) -> None:
        if self.worker is not None:
            await self.worker.queue_frame(
                OutputAudioRawFrame(audio=self._filler, sample_rate=SAMPLE_RATE, num_channels=1)
            )


def make_stt(settings: AgentSettings) -> STTService:
    if settings.stt_provider == "elevenlabs":
        from pipecat.services.elevenlabs.stt import ElevenLabsRealtimeSTTService

        return ElevenLabsRealtimeSTTService(api_key=settings.elevenlabs_api_key)

    if settings.stt_provider == "groq":
        from countersign_agent.voice.stt import ElevenLabsTranscriber, FallbackGroqSTTService

        use_fallback = settings.stt_fallback_elevenlabs and settings.elevenlabs_api_key
        return FallbackGroqSTTService(
            api_key=settings.groq_api_key,
            settings=FallbackGroqSTTService.Settings(model=settings.groq_stt_model),
            fallback=ElevenLabsTranscriber(settings.elevenlabs_api_key) if use_fallback else None,
            groq_timeout_s=settings.groq_stt_timeout_s,
            cooldown_s=settings.groq_stt_cooldown_s,
        )

    from pipecat.services.whisper.stt import WhisperSTTService

    device = settings.whisper_device
    # float16 on the GPU; int8 is the fast CPU fallback when CUDA is not available.
    compute_type = "int8" if device == "cpu" else "default"
    return WhisperSTTService(
        settings=WhisperSTTService.Settings(
            model=settings.whisper_model,
            initial_prompt=settings.whisper_initial_prompt or None,
            hotwords=settings.whisper_hotwords or None,
        ),
        device=device,
        compute_type=compute_type,
    )


def make_tts(settings: AgentSettings) -> ElevenLabsTTSService:
    return ElevenLabsTTSService(
        api_key=settings.elevenlabs_api_key,
        settings=ElevenLabsTTSService.Settings(
            voice=settings.elevenlabs_voice_id, model=settings.elevenlabs_tts_model
        ),
    )


async def run_audio_call(
    call_id: str,
    transport: BaseTransport,
    factory: GatewayFactory,
    settings: AgentSettings,
    *,
    stt: STTService | None = None,
) -> None:
    """Run one call until the caller hangs up. Always closes the gateway."""
    filler = await load_filler(
        settings.hold_filler_cache(),
        api_key=settings.elevenlabs_api_key,
        voice_id=settings.elevenlabs_voice_id,
        model_id=settings.elevenlabs_tts_model,
    )
    gateway = await factory.open_call(call_id)
    core: CallCore | None = None
    try:
        output = AudioCallOutput(filler)
        core = CallCore(
            call_id,
            gateway,
            settings,
            output,
            user_params=LLMUserAggregatorParams(vad_analyzer=make_vad(settings)),
        )
        await _run_pipeline(call_id, transport, core, output, settings, stt)
    finally:
        if core is not None:
            await core.close()
            turns = [t.model_dump() for t in core.metrics.turns]
            logger.info("call %s ended; turns: %s", call_id, turns)
        else:
            await gateway.close()


async def _run_pipeline(
    call_id: str,
    transport: BaseTransport,
    core: CallCore,
    output: AudioCallOutput,
    settings: AgentSettings,
    stt: STTService | None,
) -> None:
    if stt is None:
        # Building Whisper loads (and on first use downloads) the model synchronously. Off the
        # event loop, so a slow load can't freeze every other call and the WebRTC handshake.
        stt = await asyncio.to_thread(make_stt, settings)
    recorder = InboundAudioRecorder() if settings.debug_record_dir else None
    pipeline = Pipeline(
        [
            transport.input(),
            *([recorder] if recorder else []),
            stt,
            core.aggregators.user(),
            core.llm,
            make_tts(settings),
            transport.output(),
            core.aggregators.assistant(),
        ]
    )
    latency = UserBotLatencyObserver()

    @latency.event_handler("on_latency_measured")
    async def _on_latency(_observer: Any, seconds: float) -> None:
        core.metrics.record_user_to_bot(seconds)

    worker = PipelineWorker(
        pipeline,
        params=PipelineParams(
            audio_out_sample_rate=SAMPLE_RATE, enable_metrics=True, enable_usage_metrics=True
        ),
        observers=[core.metrics, latency],
        idle_timeout_secs=300,
    )
    output.worker = worker

    @transport.event_handler("on_client_disconnected")
    async def _on_disconnected(_transport: Any, _client: Any) -> None:
        logger.info("call %s: caller hung up", call_id)
        # Cancel holds before the pipeline goes away, so no held tool runs after hangup.
        await core.router.close()
        await worker.cancel(reason="caller hung up")

    runner = WorkerRunner(handle_sigint=False)
    await runner.add_workers(worker)
    try:
        await runner.run()
    finally:
        if recorder is not None and settings.debug_record_dir is not None:
            await recorder.save(settings.debug_record_dir / f"{call_id}.wav")
