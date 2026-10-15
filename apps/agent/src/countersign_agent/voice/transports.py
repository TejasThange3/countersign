"""Transports for the two audio entry points: the browser (SmallWebRTC) and the caller
simulator (a plain WebSocket carrying raw PCM)."""

from __future__ import annotations

from fastapi import WebSocket
from pipecat.frames.frames import Frame, InputAudioRawFrame, OutputAudioRawFrame
from pipecat.serializers.base_serializer import FrameSerializer
from pipecat.transports.base_transport import TransportParams
from pipecat.transports.smallwebrtc.connection import SmallWebRTCConnection
from pipecat.transports.smallwebrtc.transport import SmallWebRTCTransport
from pipecat.transports.websocket.fastapi import (
    FastAPIWebsocketParams,
    FastAPIWebsocketTransport,
)

# The simulator protocol: binary messages only. Caller -> agent is 16 kHz mono PCM16,
# agent -> caller is 24 kHz mono PCM16. Nothing else is sent, so any client can speak it.
SIM_IN_SAMPLE_RATE = 16_000


class RawPCMSerializer(FrameSerializer):
    async def serialize(self, frame: Frame) -> bytes | None:
        if isinstance(frame, OutputAudioRawFrame):
            return frame.audio
        return None

    async def deserialize(self, data: str | bytes) -> Frame | None:
        if isinstance(data, bytes) and data:
            return InputAudioRawFrame(audio=data, sample_rate=SIM_IN_SAMPLE_RATE, num_channels=1)
        return None


def webrtc_transport(connection: SmallWebRTCConnection) -> SmallWebRTCTransport:
    return SmallWebRTCTransport(
        webrtc_connection=connection,
        params=TransportParams(audio_in_enabled=True, audio_out_enabled=True),
    )


def simulator_transport(websocket: WebSocket) -> FastAPIWebsocketTransport:
    return FastAPIWebsocketTransport(
        websocket=websocket,
        params=FastAPIWebsocketParams(
            audio_in_enabled=True,
            audio_out_enabled=True,
            audio_in_sample_rate=SIM_IN_SAMPLE_RATE,
            serializer=RawPCMSerializer(),
        ),
    )
