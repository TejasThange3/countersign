"""Hosted speech-to-text: Groq Whisper first, ElevenLabs Scribe when Groq can't answer.

The live demo runs for days on Groq's free tier (about 20 transcriptions a minute). When Groq
errors, times out or rate-limits, the same utterance goes to ElevenLabs instead and Groq is
skipped for a cooldown, so the caller hears no gap. ElevenLabs costs credits, so it is only
ever the fallback.
"""

from __future__ import annotations

import asyncio
import io
import logging
import time
from typing import Protocol

import aiohttp
from openai.types.audio import Transcription
from pipecat.services.groq.stt import GroqSTTService

logger = logging.getLogger(__name__)

ELEVENLABS_STT_URL = "https://api.elevenlabs.io/v1/speech-to-text"


class Transcriber(Protocol):
    async def transcribe(self, wav: bytes) -> str: ...

    async def aclose(self) -> None: ...


class ElevenLabsTranscriber:
    """One-shot ElevenLabs Scribe transcription of a finished utterance (WAV bytes)."""

    def __init__(self, api_key: str, model: str = "scribe_v2", timeout_s: float = 10.0) -> None:
        self._api_key = api_key
        self._model = model
        self._timeout = aiohttp.ClientTimeout(total=timeout_s)
        self._session: aiohttp.ClientSession | None = None

    async def transcribe(self, wav: bytes) -> str:
        if self._session is None:
            self._session = aiohttp.ClientSession(timeout=self._timeout)
        form = aiohttp.FormData()
        form.add_field("file", io.BytesIO(wav), filename="audio.wav", content_type="audio/x-wav")
        form.add_field("model_id", self._model)
        form.add_field("language_code", "en")
        headers = {"xi-api-key": self._api_key}
        async with self._session.post(ELEVENLABS_STT_URL, data=form, headers=headers) as resp:
            if resp.status != 200:
                raise RuntimeError(f"ElevenLabs STT {resp.status}: {await resp.text()}")
            body = await resp.json()
        return str(body.get("text", "")).strip()

    async def aclose(self) -> None:
        if self._session is not None:
            await self._session.close()
            self._session = None


class FallbackGroqSTTService(GroqSTTService):
    """Groq Whisper with a per-utterance fallback and a cooldown after a Groq failure."""

    def __init__(
        self,
        *,
        fallback: Transcriber | None,
        groq_timeout_s: float = 6.0,
        cooldown_s: float = 60.0,
        **kwargs: object,
    ) -> None:
        super().__init__(**kwargs)  # type: ignore[arg-type]
        self._fallback = fallback
        self._groq_timeout_s = groq_timeout_s
        self._cooldown_s = cooldown_s
        self._groq_skip_until = 0.0

    async def _transcribe(self, audio: bytes) -> Transcription:
        if self._fallback is None:
            return await asyncio.wait_for(super()._transcribe(audio), self._groq_timeout_s)
        if time.monotonic() >= self._groq_skip_until:
            try:
                return await asyncio.wait_for(super()._transcribe(audio), self._groq_timeout_s)
            except Exception as exc:  # any Groq failure: rate limit, timeout, 5xx, network
                self._groq_skip_until = time.monotonic() + self._cooldown_s
                logger.warning(
                    "Groq STT failed (%s: %s); using ElevenLabs for %.0f s",
                    type(exc).__name__,
                    exc,
                    self._cooldown_s,
                )
        return Transcription(text=await self._fallback.transcribe(audio))

    async def cleanup(self) -> None:
        await super().cleanup()
        if self._fallback is not None:
            await self._fallback.aclose()
