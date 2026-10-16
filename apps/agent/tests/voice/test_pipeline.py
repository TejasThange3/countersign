"""Audio-call lifecycle that can be checked without audio: the gateway always closes."""

from __future__ import annotations

from typing import Any

import pytest
from countersign_agent.voice import pipeline
from countersign_agent.voice.fake_gateway import FakeGatewayFactory
from fakes import make_settings


async def test_gateway_closes_when_pipeline_setup_fails(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    async def broken(*_args: Any, **_kwargs: Any) -> None:
        raise RuntimeError("whisper model failed to load")

    monkeypatch.setattr(pipeline, "_run_pipeline", broken)
    factory = FakeGatewayFactory()
    settings = make_settings(hold_filler_cache_dir=tmp_path, groq_api_key="fake-key")

    with pytest.raises(RuntimeError):
        await pipeline.run_audio_call("c1", object(), factory, settings)  # type: ignore[arg-type]

    assert factory.opened[0].closed


@pytest.mark.parametrize(
    ("overrides", "prompt", "hotwords"),
    [
        ({}, None, None),  # off by default: a prompt broke distil-medium.en transcription
        (
            {"whisper_initial_prompt": "LRK-1001", "whisper_hotwords": "Okafor"},
            "LRK-1001",
            "Okafor",
        ),
    ],
)
def test_whisper_vocabulary_is_opt_in(
    monkeypatch: pytest.MonkeyPatch,
    overrides: dict[str, str],
    prompt: str | None,
    hotwords: str | None,
) -> None:
    from pipecat.services.whisper import stt as whisper_stt

    built: dict[str, Any] = {}

    class RecordingWhisper:
        Settings = whisper_stt.WhisperSTTService.Settings

        def __init__(self, *, settings: Any, **kwargs: Any) -> None:
            built["settings"] = settings

    monkeypatch.setattr(whisper_stt, "WhisperSTTService", RecordingWhisper)
    pipeline.make_stt(make_settings(**overrides))

    assert built["settings"].initial_prompt == prompt
    assert built["settings"].hotwords == hotwords


def test_groq_stt_uses_the_groq_key_and_model(monkeypatch: pytest.MonkeyPatch) -> None:
    from pipecat.services.groq import stt as groq_stt

    built: dict[str, Any] = {}

    class RecordingGroq:
        Settings = groq_stt.GroqSTTService.Settings

        def __init__(self, *, api_key: str, settings: Any, **kwargs: Any) -> None:
            built["api_key"] = api_key
            built["settings"] = settings

    monkeypatch.setattr(groq_stt, "GroqSTTService", RecordingGroq)
    pipeline.make_stt(
        make_settings(stt_provider="groq", groq_api_key="fake-key", groq_stt_model="m-1")
    )

    assert built["api_key"] == "fake-key"
    assert built["settings"].model == "m-1"


def test_groq_stt_builds_without_network() -> None:
    from pipecat.services.groq.stt import GroqSTTService

    stt = pipeline.make_stt(make_settings(stt_provider="groq", groq_api_key="fake-key"))

    assert isinstance(stt, GroqSTTService)
