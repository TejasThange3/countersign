"""Hold filler audio that never spends TTS credits per hold.

The spoken filler line is synthesized by ElevenLabs once, cached to disk as raw PCM and
replayed from then on. If it can't be made (no key, API error), a soft generated two-note
tone is used instead. Only the hold announcement and the outcome line are spoken live.
"""

from __future__ import annotations

import array
import asyncio
import logging
import math
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)

SAMPLE_RATE = 24_000
FILLER_TEXT = "Still checking with the manager. Thanks for holding."


def hold_tone(sample_rate: int = SAMPLE_RATE) -> bytes:
    """A quiet two-note chime (16-bit mono PCM), about 0.7 seconds."""
    samples = array.array("h")
    for freq, seconds in ((660.0, 0.25), (880.0, 0.35)):
        n = int(sample_rate * seconds)
        for i in range(n):
            fade = min(1.0, i / (0.02 * sample_rate), (n - i) / (0.08 * sample_rate))
            samples.append(int(3000 * fade * math.sin(2 * math.pi * freq * i / sample_rate)))
    samples.extend([0] * int(sample_rate * 0.1))
    return samples.tobytes()


async def load_filler(cache: Path, *, api_key: str, voice_id: str, model_id: str) -> bytes:
    """Cached spoken filler if present, else synthesize it once, else the tone."""
    cached = await asyncio.to_thread(_read_cache, cache)
    if cached:
        return cached
    if not api_key:
        return hold_tone()
    try:
        audio = await _synthesize(api_key, voice_id, model_id)
    except httpx.HTTPError:
        logger.exception("could not synthesize hold filler; using the hold tone")
        return hold_tone()
    try:
        await asyncio.to_thread(_write_cache, cache, audio)
    except OSError:
        # Still usable for this call; it just gets synthesized again next time.
        logger.exception("could not cache hold filler at %s", cache)
    else:
        logger.info("hold filler synthesized once and cached at %s", cache)
    return audio


def _read_cache(cache: Path) -> bytes | None:
    return cache.read_bytes() if cache.is_file() and cache.stat().st_size > 0 else None


def _write_cache(cache: Path, audio: bytes) -> None:
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_bytes(audio)


async def _synthesize(api_key: str, voice_id: str, model_id: str) -> bytes:
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(
            f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}",
            params={"output_format": f"pcm_{SAMPLE_RATE}"},
            headers={"xi-api-key": api_key},
            json={"text": FILLER_TEXT, "model_id": model_id},
        )
        response.raise_for_status()
        return response.content
