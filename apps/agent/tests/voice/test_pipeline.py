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
