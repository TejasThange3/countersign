"""The VAD takes its thresholds from settings (barge-in tuning) and logs what it measured."""

from __future__ import annotations

import logging

import numpy as np
import pytest
from countersign_agent.voice import vad as vad_module
from countersign_agent.voice.vad import make_vad
from fakes import make_settings


def test_thresholds_come_from_settings() -> None:
    vad = make_vad(make_settings(vad_confidence=0.6, vad_min_volume=0.3, vad_start_secs=0.15))
    assert vad.params.confidence == 0.6
    assert vad.params.min_volume == 0.3
    assert vad.params.start_secs == 0.15


def test_default_loudness_floor_is_below_pipecats() -> None:
    # 0.6 (Pipecat's default) missed a caller talking over the bot in a live test.
    assert make_vad(make_settings()).params.min_volume < 0.6


def test_speech_like_seconds_are_logged(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    vad = make_vad(make_settings())
    vad.set_sample_rate(16000)
    # Silero really returns a numpy array; the log must still format.
    monkeypatch.setattr(
        vad_module.SileroVADAnalyzer, "voice_confidence", lambda _s, _b: np.array([[0.9]])
    )
    clock = iter([100.0, 101.5])
    monkeypatch.setattr(vad_module.time, "monotonic", lambda: next(clock))
    vad._window_started = 100.0
    with caplog.at_level(logging.INFO, logger=vad_module.__name__):
        vad.voice_confidence(b"\x00" * 1024)
        vad.voice_confidence(b"\x00" * 1024)
    assert "vad peak confidence=0.90" in caplog.text
