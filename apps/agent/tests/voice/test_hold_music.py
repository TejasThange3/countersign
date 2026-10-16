"""Hold music: generated, chunked so the outcome is never delayed, click-free at boundaries."""

from __future__ import annotations

import array

from countersign_agent.voice.filler import MUSIC_CHUNK_S, SAMPLE_RATE, hold_music
from countersign_agent.voice.pipeline import AudioCallOutput
from fakes import make_settings


def test_music_is_one_second_chunks_that_start_and_end_silent() -> None:
    chunks = hold_music()
    assert len(chunks) == 16
    for chunk in chunks:
        samples = array.array("h", chunk)
        assert len(samples) == int(SAMPLE_RATE * MUSIC_CHUNK_S)
        assert abs(samples[0]) < 200 and abs(samples[-1]) < 200  # no click at the seam
        assert 0 < max(abs(s) for s in samples) < 6000  # audible but quiet


def test_music_timing_waits_for_the_announcement_then_streams() -> None:
    start, every = make_settings(hold_audio="music", hold_music_start_s=4.5).hold_filler_timing()
    assert (start, every) == (4.5, MUSIC_CHUNK_S)
    assert make_settings(hold_audio="voice", hold_filler_interval_s=6).hold_filler_timing() == (
        6,
        6,
    )


class RecordingWorker:
    def __init__(self) -> None:
        self.frames: list[object] = []

    async def queue_frame(self, frame: object) -> None:
        self.frames.append(frame)


async def test_audio_output_loops_through_the_pieces() -> None:
    output = AudioCallOutput([b"a", b"b"])
    worker = RecordingWorker()
    output.worker = worker  # type: ignore[assignment]  # only queue_frame is used
    for _ in range(3):
        await output.play_filler()
    assert [f.audio for f in worker.frames] == [b"a", b"b", b"a"]  # type: ignore[attr-defined]


async def test_silence_plays_nothing() -> None:
    output = AudioCallOutput([])
    worker = RecordingWorker()
    output.worker = worker  # type: ignore[assignment]
    await output.play_filler()
    assert worker.frames == []
