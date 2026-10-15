"""FallbackGroqLLMService: header-timed 429 retry, fallback, pinning, model recording (no network)."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import httpx
import pytest
from countersign_agent.voice import llm as llm_module
from countersign_agent.voice.llm import FallbackGroqLLMService, parse_reset_s
from openai import APIStatusError, RateLimitError
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.services.groq.llm import GroqLLMService

PRIMARY, FALLBACK = "openai/gpt-oss-120b", "openai/gpt-oss-20b"


@pytest.fixture(autouse=True)
def clear_cooldowns() -> Iterator[None]:
    llm_module._cooldown_until.clear()
    yield
    llm_module._cooldown_until.clear()


def status_error(code: int, headers: dict[str, str] | None = None) -> APIStatusError:
    request = httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions")
    response = httpx.Response(code, headers=headers or {}, request=request)
    cls = RateLimitError if code == 429 else APIStatusError
    return cls("fake", response=response, body=None)


def make_service(
    monkeypatch: pytest.MonkeyPatch,
    behaviour: dict[str, list[Any]],
    fallback: str | None = FALLBACK,
) -> tuple[FallbackGroqLLMService, list[str], list[float]]:
    """`behaviour[model]` is consumed one entry per request: an exception is raised,
    anything else is returned as the stream."""
    requested: list[str] = []
    slept: list[float] = []

    async def fake_completions(self: GroqLLMService, context: LLMContext) -> Any:
        model = str(self._settings.model)
        requested.append(model)
        outcome = behaviour[model].pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    async def fake_sleep(seconds: float) -> None:
        slept.append(seconds)

    monkeypatch.setattr(GroqLLMService, "get_chat_completions", fake_completions)
    monkeypatch.setattr(llm_module.asyncio, "sleep", fake_sleep)
    service = FallbackGroqLLMService(
        api_key="fake-key",
        settings=GroqLLMService.Settings(model=PRIMARY),
        fallback_model=fallback,
        max_rate_limit_wait_s=10.0,
    )
    return service, requested, slept


async def run(service: FallbackGroqLLMService) -> tuple[Any, list[str]]:
    used: list[str] = []

    async def record(model: str) -> None:
        used.append(model)

    service.on_model_used = record
    return await service.get_chat_completions(LLMContext()), used


@pytest.mark.parametrize(
    ("value", "seconds"),
    [("7", 7.0), ("7.66s", 7.66), ("2m59.5s", 179.5), ("120ms", 0.12), ("1h2m", 3720.0)],
)
def test_parse_reset(value: str, seconds: float) -> None:
    assert parse_reset_s(value) == pytest.approx(seconds)


def test_parse_reset_rejects_garbage() -> None:
    assert parse_reset_s("soon") is None
    assert parse_reset_s(None) is None


async def test_primary_answers_and_is_recorded(monkeypatch: pytest.MonkeyPatch) -> None:
    service, requested, _slept = make_service(monkeypatch, {PRIMARY: ["stream"]})
    stream, used = await run(service)
    assert stream == "stream" and used == [PRIMARY] and requested == [PRIMARY]


async def test_429_waits_the_reset_header_and_retries_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    limited = status_error(429, {"x-ratelimit-reset-tokens": "2.5s"})
    service, requested, slept = make_service(monkeypatch, {PRIMARY: [limited, "stream"]})
    _stream, used = await run(service)
    assert slept == [2.5]
    assert requested == [PRIMARY, PRIMARY] and used == [PRIMARY]


async def test_second_429_falls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    limited = status_error(429, {"retry-after": "3"})
    service, requested, slept = make_service(
        monkeypatch, {PRIMARY: [limited, limited], FALLBACK: ["stream"]}
    )
    _stream, used = await run(service)
    assert slept == [3.0]
    assert requested == [PRIMARY, PRIMARY, FALLBACK] and used == [FALLBACK]
    assert service._settings.model == PRIMARY  # restored after the request


async def test_429_with_a_long_reset_falls_back_without_waiting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    limited = status_error(429, {"x-ratelimit-reset-requests": "2m59.5s"})
    service, requested, slept = make_service(
        monkeypatch, {PRIMARY: [limited], FALLBACK: ["stream"]}
    )
    _stream, used = await run(service)
    assert slept == []
    assert requested == [PRIMARY, FALLBACK] and used == [FALLBACK]


async def test_rate_limited_primary_is_skipped_until_its_reset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    limited = status_error(429, {"retry-after": "60"})
    service, requested, _slept = make_service(
        monkeypatch, {PRIMARY: [limited], FALLBACK: ["a", "b"]}
    )
    await run(service)
    await run(service)
    assert requested == [PRIMARY, FALLBACK, FALLBACK]


async def test_503_switches_at_once(monkeypatch: pytest.MonkeyPatch) -> None:
    service, requested, slept = make_service(
        monkeypatch, {PRIMARY: [status_error(503)], FALLBACK: ["stream"]}
    )
    _stream, used = await run(service)
    assert slept == [] and requested == [PRIMARY, FALLBACK] and used == [FALLBACK]


async def test_bad_request_is_raised_not_switched(monkeypatch: pytest.MonkeyPatch) -> None:
    service, requested, _slept = make_service(monkeypatch, {PRIMARY: [status_error(400)]})
    with pytest.raises(APIStatusError):
        await run(service)
    assert requested == [PRIMARY]


async def test_pinned_model_fails_loudly(monkeypatch: pytest.MonkeyPatch) -> None:
    limited = status_error(429, {"retry-after": "1"})
    service, requested, _slept = make_service(
        monkeypatch, {PRIMARY: [limited, limited]}, fallback=""
    )
    with pytest.raises(RateLimitError):
        await run(service)
    assert requested == [PRIMARY, PRIMARY]


def test_sdk_retries_are_off() -> None:
    service = FallbackGroqLLMService(
        api_key="fake-key", settings=GroqLLMService.Settings(model=PRIMARY), fallback_model=None
    )
    assert service._client.max_retries == 0


def test_requests_time_out_quickly() -> None:
    # The SDK default is 10 minutes; a hung connection held a live turn for 26 s.
    service = FallbackGroqLLMService(
        api_key="fake-key",
        settings=GroqLLMService.Settings(model=PRIMARY),
        fallback_model=None,
        request_timeout_s=8.0,
    )
    timeout = service._client.timeout
    assert timeout.connect == 8.0
    assert timeout.read == 20.0  # mid-stream pauses can no longer fall back, so allow more
