"""Hold filler audio that never spends TTS credits per hold.

Default (HOLD_AUDIO=music): soft generated hold music in one-second chunks, so the outcome
is spoken within a second of the manager's decision. With HOLD_AUDIO=voice, the spoken filler line is synthesized by ElevenLabs once, cached to disk as raw PCM and
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


MUSIC_CHUNK_S = 1.0
_BEAT_S = 0.5
# A slow I-vi-IV-V loop (C, Am, F, G): a bass note and two plucked notes per one-second
# chunk, sixteen chunks before it repeats.
_LOOP = [
    (130.81, (523.25, 659.25)),
    (130.81, (783.99, 659.25)),
    (130.81, (523.25, 783.99)),
    (130.81, (659.25, 587.33)),
    (110.00, (440.00, 523.25)),
    (110.00, (659.25, 523.25)),
    (110.00, (440.00, 659.25)),
    (110.00, (587.33, 523.25)),
    (87.31, (349.23, 440.00)),
    (87.31, (523.25, 440.00)),
    (87.31, (349.23, 523.25)),
    (87.31, (440.00, 392.00)),
    (98.00, (392.00, 493.88)),
    (98.00, (587.33, 493.88)),
    (98.00, (392.00, 587.33)),
    (98.00, (493.88, 440.00)),
]


def _pluck(freq: float, n: int, sample_rate: int, peak: float, decay_s: float) -> list[float]:
    """A soft electric-piano-like note: fundamental plus quiet overtones and an exponential
    decay, faded to exactly zero at the end so chunk boundaries never click."""
    out = []
    fade_n = int(0.02 * sample_rate)
    for i in range(n):
        t = i / sample_rate
        env = math.exp(-t / decay_s) * min(1.0, i / (0.005 * sample_rate), (n - i) / fade_n)
        w = 2 * math.pi * freq * t
        out.append(peak * env * (math.sin(w) + 0.25 * math.sin(2 * w) + 0.08 * math.sin(3 * w)))
    return out


def hold_music(sample_rate: int = SAMPLE_RATE) -> list[bytes]:
    """Sixteen one-second chunks of quiet hold music (16-bit mono PCM), played in a loop."""
    chunk_n = int(sample_rate * MUSIC_CHUNK_S)
    beat_n = int(sample_rate * _BEAT_S)
    chunks = []
    for bass, notes in _LOOP:
        mix = _pluck(bass, chunk_n, sample_rate, 900.0, 0.45)
        for k, note in enumerate(notes):
            for i, v in enumerate(_pluck(note, beat_n, sample_rate, 1500.0, 0.18)):
                mix[k * beat_n + i] += v
        pcm = array.array("h", (int(max(-32767.0, min(32767.0, v))) for v in mix))
        chunks.append(pcm.tobytes())
    return chunks


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
