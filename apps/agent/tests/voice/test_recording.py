"""The dev-only inbound audio recorder writes the caller's audio as a WAV."""

from __future__ import annotations

import wave
from pathlib import Path

from countersign_agent.voice.recording import InboundAudioRecorder


async def test_inbound_audio_is_saved_as_wav(tmp_path: Path) -> None:
    recorder = InboundAudioRecorder()
    # process_frame needs a running pipeline; feed the buffer the way it would.
    recorder._audio += b"\x01\x00" * 1600
    await recorder.save(tmp_path / "call.wav")

    with wave.open(str(tmp_path / "call.wav"), "rb") as wav:
        assert wav.getframerate() == 16000
        assert wav.getnframes() == 1600


async def test_nothing_is_written_without_audio(tmp_path: Path) -> None:
    await InboundAudioRecorder().save(tmp_path / "empty.wav")
    assert not (tmp_path / "empty.wav").exists()
