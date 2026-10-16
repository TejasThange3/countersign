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

    # Which LLM answers calls. Groq is the default: Gemini's free tier ran out of daily quota
    # (20 requests per model) during development. Gemini stays available.
    llm_provider: Literal["groq", "gemini"] = "groq"

    groq_api_key: str = ""
    # Groq models (Gemini uses GEMINI_MODEL / GEMINI_FALLBACK_MODEL below). Each Groq model
    # has its own rate limits, so the fallback also absorbs a 429 on the primary. Every turn
    # records which model answered. LLM_FALLBACK_MODEL= (empty) pins one model for evals.
    llm_model: str = "openai/gpt-oss-120b"
    llm_fallback_model: str | None = "openai/gpt-oss-20b"
    # gpt-oss reasons before answering; "low" keeps a phone turn fast.
    llm_reasoning_effort: Literal["low", "medium", "high"] = "low"
    # On a 429, wait what Groq's reset headers say and retry once, if that is no longer than
    # this; otherwise (or if the retry also fails) move to the fallback model.
    llm_rate_limit_max_wait_s: float = 10.0
    # After a failure, skip that Groq model (unless it's the only option) for this long, or
    # for as long as its rate-limit reset header says.
    llm_model_cooldown_s: float = 60.0
    # Per-request timeout for Groq (connect and between streamed bytes). A connection that
    # hung for 26 s was seen live; past this, the request fails over to the fallback model.
    llm_request_timeout_s: float = Field(default=8.0, gt=0)

    gemini_api_key: str = ""
    gemini_model: str = "gemini-3.8-flash"
    # Used only when the primary model is rate limited or unavailable; every turn records
    # which model answered, so a switch is never silent. Set GEMINI_FALLBACK_MODEL= (empty)
    # to pin one model, e.g. for with/without-ArmorIQ eval runs that must use the same model:
    # then a failing primary fails the turn loudly instead of switching.
    gemini_fallback_model: str | None = "gemini-3.5-flash"
    # Rate-limit retries on one model before moving to the next.
    gemini_rate_limit_retries: int = 2
    gemini_rate_limit_backoff_s: float = 2.0
    # A model that accepts a request but streams nothing for this long is skipped.
    gemini_first_chunk_timeout_s: float = 10.0
    # The last model left (or the only one, when pinned) waits this long instead: silence is
    # worse than a slow answer.
    gemini_last_model_timeout_s: float = 30.0
    # After a failure, skip that model (unless it's the only option) for this long. 0 = never.
    gemini_model_cooldown_s: float = 120.0

    elevenlabs_api_key: str = ""
    elevenlabs_voice_id: str = "21m00Tcm4TlvDq8ikWAM"  # "Rachel", an ElevenLabs premade voice
    elevenlabs_tts_model: str = "eleven_flash_v2_5"

    # whisper: local faster-whisper on the GPU (development). groq: Whisper on Groq's servers,
    # for hosts without a GPU (Railway); same key as the LLM, 0 ElevenLabs credits.
    stt_provider: Literal["whisper", "groq", "elevenlabs"] = "whisper"
    # Groq's hosted Whisper; turbo is the fast, cheap one and handles English well.
    groq_stt_model: str = "whisper-large-v3-turbo"
    # Format hint for Groq Whisper. Measured on synthesized clips: it writes "LRK-1001"
    # instead of "LRK1001" and changed nothing else. Set GROQ_STT_PROMPT= (empty) to disable.
    groq_stt_prompt: str = "Hotel front desk call. Booking references look like LRK-1001."
    # With STT_PROVIDER=groq: send an utterance to ElevenLabs Scribe when Groq fails or
    # rate-limits, then skip Groq for the cooldown. Costs ElevenLabs credits only when used.
    stt_fallback_elevenlabs: bool = True
    groq_stt_timeout_s: float = Field(default=6.0, gt=0)
    groq_stt_cooldown_s: float = Field(default=60.0, ge=0)
    # Measured on the same recorded call: distil-large-v3 got "My booking reference is LRK
    # 1001. Last name, Okafor." exactly; distil-medium.en lost the name and turned the number
    # into "1,000". Large runs on the GPU (186 s of audio in 1.4 s). distil-medium.en (~400 MB)
    # remains the fallback for a machine short on memory.
    whisper_model: str = "distil-large-v3"
    whisper_device: Literal["cuda", "cpu", "auto"] = "auto"
    # Optional domain context for Whisper (`initial_prompt`: preceding text the decoder
    # continues from; `hotwords`: words to bias towards). OFF by default, from a measurement:
    # on a recorded call, distil-medium.en with a prompt cut "Do you have a room on November
    # 2nd for two nights?" to "Do you have a room?" and live it returned nothing at all;
    # hotwords alone raised no_speech_prob from 0.01 to 0.27 (Pipecat drops text at 0.4).
    # Misheard numbers are handled by the agent reading references back instead.
    whisper_initial_prompt: str = ""
    whisper_hotwords: str = ""
    # Dev only: save each call's inbound (caller) audio as <dir>/<call_id>.wav to compare STT
    # models on the same speech. Off when unset. Records the microphone: own test calls only.
    debug_record_dir: Path | None = None

    # Silero VAD thresholds. Speech counts when confidence AND loudness (0-1, from -110 to
    # -10 LUFS) both clear them. Pipecat's defaults (0.7 / 0.6) missed a caller talking over
    # the bot in a live test: browser echo cancellation turns the caller down during bot
    # playback. The VAD logs its peak values to tune these from evidence.
    vad_confidence: float = Field(default=0.7, ge=0, le=1)
    vad_min_volume: float = Field(default=0.4, ge=0, le=1)
    vad_start_secs: float = Field(default=0.2, gt=0)
    # Silence that ends a speech segment. Each segment is transcribed on its own, so Pipecat's
    # 0.2 s split "LRK 1001 ... last name Okafor" into fragments in a live call, and Whisper,
    # given half a second with no context, heard "Okay for". 0.5 s keeps a sentence together.
    vad_stop_secs: float = Field(default=0.5, gt=0)

    hold_timeout_s: float = Field(default=60.0, gt=0)
    hold_filler_interval_s: float = Field(default=6.0, gt=0)
    # Spoken filler is synthesized once and cached here (outside the repo, keyed by voice and
    # model); without an ElevenLabs key a generated hold tone is played instead.
    hold_filler_cache_dir: Path = Path.home() / ".cache" / "countersign"

    def hold_filler_cache(self) -> Path:
        name = f"hold_filler_{self.elevenlabs_voice_id}_{self.elevenlabs_tts_model}.pcm"
        return self.hold_filler_cache_dir / name

    # Loopback by default; a deployment that must listen publicly sets AGENT_HOST explicitly.
    agent_host: str = "127.0.0.1"
    agent_port: int = 7860
