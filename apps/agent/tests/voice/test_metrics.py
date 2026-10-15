"""TurnMetricsRecorder: TTS character counting (the ElevenLabs credit spend) and TTFB."""

from __future__ import annotations

from countersign_agent.voice.metrics import TurnMetricsRecorder
from pipecat.frames.frames import MetricsFrame
from pipecat.metrics.metrics import MetricsData, TTFBMetricsData, TTSUsageMetricsData
from pipecat.observers.base_observer import FramePushed
from pipecat.processors.frame_processor import FrameDirection
from pipecat.services.tts_service import TTSService


class FakeTTS(TTSService):
    async def run_tts(self, *_args: object, **_kwargs: object) -> None:  # type: ignore[override]
        raise NotImplementedError


def tts_metrics(*data: MetricsData) -> FramePushed:
    # Only the source's type matters to the recorder, so skip the service's constructor.
    source = FakeTTS.__new__(FakeTTS)
    return FramePushed(
        source=source,
        destination=source,
        frame=MetricsFrame(data=list(data)),
        direction=FrameDirection.DOWNSTREAM,
        timestamp=0,
        first_push=True,
    )


async def test_tts_characters_add_up_and_first_ttfb_is_kept() -> None:
    recorder = TurnMetricsRecorder("c1", turns_from_speech=False)
    recorder.start_turn()
    await recorder.on_push_frame(
        tts_metrics(
            TTFBMetricsData(processor="tts", value=0.25),
            TTSUsageMetricsData(processor="tts", value=58),
        )
    )
    await recorder.on_push_frame(
        tts_metrics(
            TTFBMetricsData(processor="tts", value=0.4),
            TTSUsageMetricsData(processor="tts", value=42),
        )
    )
    assert recorder.current.tts_characters == 100
    assert recorder.current.tts_ttfb_ms == 250.0


async def test_a_turn_with_only_tts_usage_is_not_reused() -> None:
    recorder = TurnMetricsRecorder("c1", turns_from_speech=False)
    recorder.start_turn()
    await recorder.on_push_frame(tts_metrics(TTSUsageMetricsData(processor="tts", value=10)))
    recorder.start_turn()
    assert [t.tts_characters for t in recorder.turns] == [10, 0]
