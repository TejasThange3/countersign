"""The browser WebSocket protocol: binary PCM both ways, JSON text for events."""

from __future__ import annotations

import json

from countersign_agent.voice.transports import BrowserSerializer
from pipecat.frames.frames import (
    InputAudioRawFrame,
    OutputAudioRawFrame,
    OutputTransportMessageUrgentFrame,
)


async def test_audio_out_is_raw_bytes_and_events_are_json() -> None:
    s = BrowserSerializer()
    audio = OutputAudioRawFrame(audio=b"\x01\x02", sample_rate=24_000, num_channels=1)
    assert await s.serialize(audio) == b"\x01\x02"
    event = OutputTransportMessageUrgentFrame(message={"type": "caller", "text": "hi"})
    assert json.loads(await s.serialize(event)) == {"type": "caller", "text": "hi"}  # type: ignore[arg-type]


async def test_caller_audio_in_and_text_ignored() -> None:
    s = BrowserSerializer()
    frame = await s.deserialize(b"\x00\x00")
    assert isinstance(frame, InputAudioRawFrame) and frame.sample_rate == 16_000
    assert await s.deserialize('{"type":"ping"}') is None


async def test_pipecat_rtvi_messages_are_not_forwarded() -> None:
    rtvi = OutputTransportMessageUrgentFrame(
        message={"label": "rtvi-ai", "type": "bot-tts-text", "data": {"text": "hi"}}
    )
    assert await BrowserSerializer().serialize(rtvi) is None
