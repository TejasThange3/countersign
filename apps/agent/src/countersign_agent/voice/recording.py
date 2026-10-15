"""Dev-only: keep the caller's inbound audio so STT models can be compared on the same speech.

Off unless DEBUG_RECORD_DIR is set. The audio stays in memory during the call (no file I/O on
the event loop) and is written as one WAV per call when the call ends. It records the
caller's microphone, so only turn it on for your own test calls.
"""

from __future__ import annotations

import asyncio
import logging
import wave
from pathlib import Path

from pipecat.frames.frames import Frame, InputAudioRawFrame
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

logger = logging.getLogger(__name__)


class InboundAudioRecorder(FrameProcessor):
    def __init__(self) -> None:
        super().__init__()
        self._audio = bytearray()
        self._sample_rate = 16000

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)
        if isinstance(frame, InputAudioRawFrame):
            self._audio += frame.audio
            self._sample_rate = frame.sample_rate
        await self.push_frame(frame, direction)

    async def save(self, path: Path) -> None:
        if not self._audio:
            return
        await asyncio.to_thread(_write_wav, path, bytes(self._audio), self._sample_rate)
        logger.info(
            "caller audio saved to %s (%.1f s)", path, len(self._audio) / 2 / self._sample_rate
        )


def _write_wav(path: Path, audio: bytes, sample_rate: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(audio)
