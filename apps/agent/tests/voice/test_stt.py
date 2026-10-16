"""Groq-first speech-to-text falls back to ElevenLabs (fake transcribers; no network)."""

from __future__ import annotations

import asyncio

import pytest
from countersign_agent.voice import stt as stt_module
from countersign_agent.voice.stt import FallbackGroqSTTService
from openai.types.audio import Transcription


class FakeFallback:
    """Stands in for ElevenLabs: records each utterance it was asked to transcribe."""

    def __init__(self) -> None:
        self.calls: list[bytes] = []
        self.closed = False

    async def transcribe(self, wav: bytes) -> str:
        self.calls.append(wav)
        return "from fallback"

    async def aclose(self) -> None:
        self.closed = True


def make(
    monkeypatch: pytest.MonkeyPatch, groq: object, fallback: FakeFallback | None, **kw: float
) -> FallbackGroqSTTService:
    async def fake_groq(self: object, audio: bytes) -> Transcription:
        if isinstance(groq, Exception):
            raise groq
        if groq == "hang":
            await asyncio.sleep(10)
        return Transcription(text="from groq")

    monkeypatch.setattr(stt_module.GroqSTTService, "_transcribe", fake_groq)
    return FallbackGroqSTTService(api_key="g", fallback=fallback, **kw)


async def test_groq_answers_and_fallback_is_unused(monkeypatch: pytest.MonkeyPatch) -> None:
    fb = FakeFallback()
    svc = make(monkeypatch, "ok", fb)

    assert (await svc._transcribe(b"a")).text == "from groq"
    assert fb.calls == []


async def test_groq_error_uses_fallback_then_skips_groq(monkeypatch: pytest.MonkeyPatch) -> None:
    fb = FakeFallback()
    svc = make(monkeypatch, RuntimeError("429 rate limit"), fb, cooldown_s=60)

    assert (await svc._transcribe(b"a")).text == "from fallback"
    # Inside the cooldown Groq is not tried again: still the fallback, no new Groq error.
    monkeypatch.setattr(stt_module.GroqSTTService, "_transcribe", None)
    assert (await svc._transcribe(b"b")).text == "from fallback"
    assert fb.calls == [b"a", b"b"]


async def test_groq_timeout_uses_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    fb = FakeFallback()
    svc = make(monkeypatch, "hang", fb, groq_timeout_s=0.05)

    assert (await svc._transcribe(b"a")).text == "from fallback"


async def test_groq_retried_after_cooldown(monkeypatch: pytest.MonkeyPatch) -> None:
    fb = FakeFallback()
    svc = make(monkeypatch, RuntimeError("boom"), fb, cooldown_s=0)
    await svc._transcribe(b"a")

    async def groq_back(self: object, audio: bytes) -> Transcription:
        return Transcription(text="from groq")

    monkeypatch.setattr(stt_module.GroqSTTService, "_transcribe", groq_back)
    assert (await svc._transcribe(b"b")).text == "from groq"


async def test_without_fallback_groq_errors_propagate(monkeypatch: pytest.MonkeyPatch) -> None:
    svc = make(monkeypatch, RuntimeError("boom"), None)

    with pytest.raises(RuntimeError):
        await svc._transcribe(b"a")
