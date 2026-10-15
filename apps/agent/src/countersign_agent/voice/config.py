"""Settings for the voice agent and its FastAPI app, read from the environment / `.env`."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

FAKE_GATEWAY_FACTORY = "countersign_agent.voice.fake_gateway:factory"


def _find_env_file() -> Path | None:
    """The nearest `.env` walking up from this file (the repo root in every worktree)."""
    for parent in Path(__file__).resolve().parents:
        candidate = parent / ".env"
        if candidate.is_file():
            return candidate
    return None


class AgentSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=_find_env_file(), extra="ignore")

    # "module.path:attribute" of the GatewayFactory. The fake is for dev and tests only; the
    # bridge lane's real factory replaces it with an env change, not a code change.
    gateway_factory: str = FAKE_GATEWAY_FACTORY

    gemini_api_key: str = ""
    gemini_model: str = "gemini-3.8-flash"
    # Used only when the primary model is rate limited or unavailable; every turn records
    # which model answered, so a switch is never silent.
    gemini_fallback_model: str | None = "gemini-3.5-flash"
    # Rate-limit retries on one model before moving to the next.
    gemini_rate_limit_retries: int = 2
    gemini_rate_limit_backoff_s: float = 2.0
    # A model that accepts a request but streams nothing for this long is skipped.
    gemini_first_chunk_timeout_s: float = 10.0

    elevenlabs_api_key: str = ""
    elevenlabs_voice_id: str = "21m00Tcm4TlvDq8ikWAM"  # "Rachel", an ElevenLabs premade voice
    elevenlabs_tts_model: str = "eleven_flash_v2_5"

    stt_provider: Literal["whisper", "elevenlabs"] = "whisper"
    whisper_model: str = "distil-large-v3"
    whisper_device: Literal["cuda", "cpu", "auto"] = "auto"

    hold_timeout_s: float = Field(default=60.0, gt=0)
    hold_filler_interval_s: float = Field(default=6.0, gt=0)
    # Spoken filler is synthesized once and cached here; without it a hold tone is played.
    hold_filler_cache: Path = Path(".cache/hold_filler.pcm")

    # Loopback by default; a deployment that must listen publicly sets AGENT_HOST explicitly.
    agent_host: str = "127.0.0.1"
    agent_port: int = 7860
