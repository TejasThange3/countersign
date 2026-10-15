"""Per-turn latency and model records, collected by watching the pipeline.

For every user turn we keep:
- `stt_final_ms`: user stopped speaking -> final transcript (audio mode only),
- `llm_ttft_ms`: the LLM's first time-to-first-answer-token (or TTFB) of the turn,
- `tts_ttfb_ms`: the TTS service's first time-to-first-byte of the turn (audio mode only),
- `user_to_bot_ms`: user stopped speaking -> bot started speaking (audio mode only),
- `tts_characters`: characters synthesized by TTS in the turn (audio mode only; credit spend),
- `llm_prompt_tokens` / `llm_completion_tokens`: tokens of each LLM request in the turn,
- `models`: every LLM model that answered in the turn, so a fallback is always visible.
"""

from __future__ import annotations

import logging
import time

from pipecat.frames.frames import (
    MetricsFrame,
    TranscriptionFrame,
    UserStartedSpeakingFrame,
    UserStoppedSpeakingFrame,
)
from pipecat.metrics.metrics import (
    LLMUsageMetricsData,
    TTFATMetricsData,
    TTFBMetricsData,
    TTSUsageMetricsData,
)
from pipecat.observers.base_observer import BaseObserver, FramePushed
from pipecat.services.llm_service import LLMService
from pipecat.services.stt_service import STTService
from pipecat.services.tts_service import TTSService
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class TurnMetrics(BaseModel):
    turn: int
    stt_final_ms: float | None = None
    llm_ttft_ms: float | None = None
    tts_ttfb_ms: float | None = None
    user_to_bot_ms: float | None = None
    # Characters sent to TTS in the turn: what ElevenLabs bills (cached filler is not counted
    # because it never reaches the TTS service).
    tts_characters: int = 0
    # Tokens per LLM request in the turn, so evals can pace against tokens-per-minute limits.
    llm_prompt_tokens: list[int] = Field(default_factory=list)
    llm_completion_tokens: list[int] = Field(default_factory=list)
    models: list[str] = Field(default_factory=list)


def _is_empty(turn: TurnMetrics) -> bool:
    timings = (turn.stt_final_ms, turn.llm_ttft_ms, turn.tts_ttfb_ms, turn.user_to_bot_ms)
    counted = turn.models or turn.tts_characters or turn.llm_prompt_tokens
    return not counted and all(v is None for v in timings)


class TurnMetricsRecorder(BaseObserver):
    """Pipeline observer. Text mode starts turns itself with `start_turn()`."""

    def __init__(self, call_id: str, *, turns_from_speech: bool = True) -> None:
        super().__init__()
        self._call_id = call_id
        # Audio mode starts a turn when the caller starts speaking. Text mode starts turns
        # itself, because context appends there also produce user-turn frames.
        self._turns_from_speech = turns_from_speech
        self.turns: list[TurnMetrics] = []
        self._ttfat_turn: int | None = None
        self._user_stopped_at: float | None = None

    @property
    def current(self) -> TurnMetrics:
        if not self.turns:
            self.start_turn()
        return self.turns[-1]

    def start_turn(self) -> TurnMetrics:
        if self.turns:
            if _is_empty(self.turns[-1]):
                # Nothing recorded yet (e.g. created by the pipeline's startup metrics).
                return self.turns[-1]
            self._log(self.turns[-1])
        self.turns.append(TurnMetrics(turn=len(self.turns) + 1))
        return self.turns[-1]

    async def record_model(self, model: str) -> None:
        if model not in self.current.models:
            self.current.models.append(model)

    def record_user_to_bot(self, seconds: float) -> None:
        if self.current.user_to_bot_ms is None:
            self.current.user_to_bot_ms = round(seconds * 1000, 1)

    def finish(self) -> None:
        if self.turns:
            self._log(self.turns[-1])

    async def on_push_frame(self, data: FramePushed) -> None:
        frame = data.frame
        # Observers see a frame once per hop; only the first push counts.
        if not data.first_push:
            return

        if isinstance(frame, UserStartedSpeakingFrame) and self._turns_from_speech:
            self.start_turn()
        elif isinstance(frame, UserStoppedSpeakingFrame):
            self._user_stopped_at = time.monotonic()
        elif isinstance(frame, TranscriptionFrame) and self._user_stopped_at is not None:
            if self.current.stt_final_ms is None:
                elapsed = time.monotonic() - self._user_stopped_at
                self.current.stt_final_ms = round(elapsed * 1000, 1)
        elif isinstance(frame, MetricsFrame):
            self._record_metrics(frame, data.source)

    def _record_metrics(self, frame: MetricsFrame, source: object) -> None:
        turn = self.current
        for item in frame.data:
            if isinstance(source, LLMService):
                if isinstance(item, LLMUsageMetricsData):
                    # One entry per LLM request (a tool call and the reply after it are two).
                    turn.llm_prompt_tokens.append(item.value.prompt_tokens)
                    turn.llm_completion_tokens.append(item.value.completion_tokens)
                    continue
                # TTFAT (first answer token, thinking included) is what the caller feels;
                # TTFB arrives first and is kept only if no TTFAT follows.
                if isinstance(item, TTFATMetricsData) and self._ttfat_turn != turn.turn:
                    turn.llm_ttft_ms = round(item.ttfat * 1000, 1)
                    self._ttfat_turn = turn.turn
                elif isinstance(item, TTFBMetricsData) and turn.llm_ttft_ms is None:
                    if item.value > 0:
                        turn.llm_ttft_ms = round(item.value * 1000, 1)
            elif isinstance(source, TTSService):
                if isinstance(item, TTSUsageMetricsData):
                    turn.tts_characters += item.value
                elif isinstance(item, TTFBMetricsData) and item.value > 0:
                    if turn.tts_ttfb_ms is None:
                        turn.tts_ttfb_ms = round(item.value * 1000, 1)
            elif isinstance(source, STTService) and isinstance(item, TTFBMetricsData):
                # Segmented STT (Whisper) reports its processing time as TTFB; keep it as
                # the STT figure when no user-stopped timestamp was seen.
                if turn.stt_final_ms is None and item.value > 0:
                    turn.stt_final_ms = round(item.value * 1000, 1)

    def _log(self, turn: TurnMetrics) -> None:
        logger.info("call %s turn metrics: %s", self._call_id, turn.model_dump_json())
