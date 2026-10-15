"""Silero VAD with configurable thresholds and a log of what it actually measured.

Barge-in depends on the VAD hearing the caller *while the bot is talking*. Browser echo
cancellation turns the caller down during bot playback, so speech that clears the thresholds
in silence can miss them then. Pipecat's defaults (confidence 0.7, loudness 0.6) missed
"Actually, wait" in a live test. The thresholds come from settings, and the peak confidence
and loudness of each second with speech-like audio is logged (INFO), so a missed
interruption can be diagnosed from the log instead of guessed at.
"""

from __future__ import annotations

import logging
import time

from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.audio.vad.vad_analyzer import VADParams

from countersign_agent.voice.config import AgentSettings

logger = logging.getLogger(__name__)

# Only seconds that might contain speech are logged, so silence doesn't flood the log.
_LOG_CONFIDENCE_FLOOR = 0.3
_LOG_WINDOW_S = 1.0


class MeasuredSileroVAD(SileroVADAnalyzer):
    def __init__(self, params: VADParams) -> None:
        super().__init__(params=params)
        self._window_started = time.monotonic()
        self._peak_confidence = 0.0
        self._peak_volume = 0.0

    def voice_confidence(self, buffer: bytes) -> float:
        confidence = super().voice_confidence(buffer)
        # `_prev_volume` is the smoothed loudness of the previous chunk: close enough here.
        self._peak_confidence = max(self._peak_confidence, confidence)
        self._peak_volume = max(self._peak_volume, self._prev_volume)
        now = time.monotonic()
        if now - self._window_started >= _LOG_WINDOW_S:
            if self._peak_confidence >= _LOG_CONFIDENCE_FLOOR:
                logger.info(
                    "vad peak confidence=%.2f volume=%.2f (thresholds %.2f / %.2f)",
                    self._peak_confidence,
                    self._peak_volume,
                    self.params.confidence,
                    self.params.min_volume,
                )
            self._window_started = now
            self._peak_confidence = 0.0
            self._peak_volume = 0.0
        return confidence


def make_vad(settings: AgentSettings) -> SileroVADAnalyzer:
    return MeasuredSileroVAD(
        VADParams(
            confidence=settings.vad_confidence,
            min_volume=settings.vad_min_volume,
            start_secs=settings.vad_start_secs,
        )
    )
