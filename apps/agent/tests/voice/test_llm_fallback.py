"""FallbackGoogleLLMService: retries, fallback, cooldown and model recording (no network)."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Iterator
from typing import Any

import pytest
from countersign_agent.voice import llm as llm_module
from countersign_agent.voice.config import AgentSettings
from countersign_agent.voice.llm import FallbackGoogleLLMService
from google.genai.errors import APIError
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.services.google.llm import GoogleLLMService

PRIMARY, FALLBACK = "gemini-primary", "gemini-fallback"


@pytest.fixture(autouse=True)
def clear_cooldowns() -> Iterator[None]:
    llm_module._cooldown_until.clear()
    yield
    llm_module._cooldown_until.clear()


def make_service(
    monkeypatch: pytest.MonkeyPatch,
    behaviour: dict[str, list[Any]],
    fallback: str | None = FALLBACK,
) -> tuple[FallbackGoogleLLMService, list[str]]:
    """`behaviour[model]` is consumed one entry per request: an int is an API error code,
    "stall" never sends a chunk, anything else is streamed as the only chunk."""
    requested: list[str] = []

    async def fake_stream(self: GoogleLLMService, context: LLMContext) -> AsyncIterator[Any]:
        model = str(self._settings.model)
        requested.append(model)
        outcome = behaviour[model].pop(0)
        if isinstance(outcome, int):
            raise APIError(outcome, {"error": {"message": "fake", "status": "FAKE"}})
        if outcome == "stall":
            await asyncio.sleep(10)
        yield outcome

    service = FallbackGoogleLLMService(
        api_key="fake-key",
        settings=GoogleLLMService.Settings(model=PRIMARY),
        fallback_model=fallback,
        rate_limit_retries=2,
        backoff_s=0.0,
        first_chunk_timeout_s=0.1,
    )
    monkeypatch.setattr(GoogleLLMService, "_stream_response", fake_stream)
    return service, requested


async def collect(service: FallbackGoogleLLMService) -> tuple[list[Any], list[str]]:
    used: list[str] = []

    async def record(model: str) -> None:
        used.append(model)

    service.on_model_used = record
    chunks = [c async for c in service._stream_response(LLMContext())]
    return chunks, used


async def test_primary_answers_normally(monkeypatch: pytest.MonkeyPatch) -> None:
    service, requested = make_service(monkeypatch, {PRIMARY: ["hi"]})
    chunks, used = await collect(service)
    assert chunks == ["hi"] and used == [PRIMARY] and requested == [PRIMARY]


async def test_503_switches_to_fallback_and_is_recorded(monkeypatch: pytest.MonkeyPatch) -> None:
    service, requested = make_service(monkeypatch, {PRIMARY: [503], FALLBACK: ["hi"]})
    chunks, used = await collect(service)
    assert chunks == ["hi"]
    assert used == [FALLBACK]
    assert requested == [PRIMARY, FALLBACK]
    assert service._settings.model == PRIMARY  # restored after the turn


async def test_429_retries_primary_before_falling_back(monkeypatch: pytest.MonkeyPatch) -> None:
    service, requested = make_service(monkeypatch, {PRIMARY: [429, 429, 429], FALLBACK: ["hi"]})
    _chunks, used = await collect(service)
    assert requested == [PRIMARY, PRIMARY, PRIMARY, FALLBACK]
    assert used == [FALLBACK]


async def test_429_then_success_stays_on_primary(monkeypatch: pytest.MonkeyPatch) -> None:
    service, requested = make_service(monkeypatch, {PRIMARY: [429, "hi"]})
    _chunks, used = await collect(service)
    assert requested == [PRIMARY, PRIMARY] and used == [PRIMARY]


async def test_silent_primary_times_out_to_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    service, _requested = make_service(monkeypatch, {PRIMARY: ["stall"], FALLBACK: ["hi"]})
    chunks, used = await collect(service)
    assert chunks == ["hi"] and used == [FALLBACK]


async def test_failed_primary_is_skipped_during_cooldown(monkeypatch: pytest.MonkeyPatch) -> None:
    service, requested = make_service(monkeypatch, {PRIMARY: [503], FALLBACK: ["a", "b"]})
    await collect(service)
    await collect(service)
    assert requested == [PRIMARY, FALLBACK, FALLBACK]


async def test_non_retryable_error_is_raised(monkeypatch: pytest.MonkeyPatch) -> None:
    service, _requested = make_service(monkeypatch, {PRIMARY: [400]})
    with pytest.raises(APIError):
        await collect(service)


async def test_everything_failing_raises_last_error(monkeypatch: pytest.MonkeyPatch) -> None:
    service, _requested = make_service(monkeypatch, {PRIMARY: [503], FALLBACK: [503]})
    with pytest.raises(APIError):
        await collect(service)


async def test_empty_fallback_pins_the_model_and_fails_loudly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # GEMINI_FALLBACK_MODEL= (empty) is how eval runs pin one model.
    service, requested = make_service(monkeypatch, {PRIMARY: [503, "hi"]}, fallback="")
    with pytest.raises(APIError):
        await collect(service)
    assert requested == [PRIMARY]
    # The pinned model is never skipped for cooldown: it is the only option.
    chunks, used = await collect(service)
    assert chunks == ["hi"] and used == [PRIMARY]


def test_empty_env_value_disables_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GEMINI_FALLBACK_MODEL", "")
    settings = AgentSettings(_env_file=None)  # type: ignore[call-arg]  # pydantic-settings kwarg
    assert not settings.gemini_fallback_model


async def test_model_is_restored_before_streaming_so_abandoned_streams_cant_leak(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, _requested = make_service(monkeypatch, {PRIMARY: [503], FALLBACK: ["hi"]})
    stream = service._stream_response(LLMContext())
    assert await anext(stream) == "hi"
    # A barge-in can abandon the stream here without closing it.
    assert service._settings.model == PRIMARY
    await stream.aclose()
