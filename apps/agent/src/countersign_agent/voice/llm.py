"""LLM services with rate-limit handling and a recorded, never-silent fallback model.

Two providers, same contract: `FallbackGroqLLMService` (the default) and
`FallbackGoogleLLMService`. On a rate limit or an unavailable model they retry or move to
the fallback model, only before anything has been streamed (where these errors surface).
Every inference reports the model that actually answered through `on_model_used`, and a
fallback is logged as a warning, so evals can say which model produced each turn. With no
fallback model configured (pinned mode, for evals) a failure fails the turn loudly.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import aclosing
from typing import Any

from google.genai.errors import APIError
from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AsyncStream,
    RateLimitError,
)
from openai.types.chat import ChatCompletionChunk
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.services.google.llm import GoogleLLMService
from pipecat.services.groq.llm import GroqLLMService

logger = logging.getLogger(__name__)

ModelListener = Callable[[str], Awaitable[None]]

# Worth retrying on the same model after a backoff: rate limited.
_RETRYABLE = {429}
# Worth moving straight to the fallback: model unknown to this key (404), or overloaded /
# erroring (500, 503 "high demand", seen live on the free tier). Retrying those only adds
# seconds of silence on a phone call.
_SWITCH_NOW = {404, 500, 503}


def _daily_quota_exhausted(exc: APIError) -> bool:
    """A 429 for the per-day quota (free tier: 20 requests per model) won't clear in seconds,
    so retrying it only adds silence."""
    return exc.code == 429 and "PerDay" in str(exc.details)


# A model that just failed is skipped (unless it is the last option) for this long, so an
# overloaded primary doesn't add seconds of silence to every turn. Process-wide on purpose:
# one LLM instance exists per call, and the overload outlives any single call.
_cooldown_until: dict[str, float] = {}


def _cooling_down(model: str) -> bool:
    return time.monotonic() < _cooldown_until.get(model, 0.0)


def _start_cooldown(model: str, seconds: float) -> None:
    if seconds <= 0:
        return
    logger.warning("%s skipped for the next %.0fs after a failure", model, seconds)
    _cooldown_until[model] = time.monotonic() + seconds


class FallbackGoogleLLMService(GoogleLLMService):
    def __init__(
        self,
        *,
        fallback_model: str | None,
        rate_limit_retries: int = 2,
        backoff_s: float = 2.0,
        first_chunk_timeout_s: float = 10.0,
        last_model_timeout_s: float = 30.0,
        cooldown_s: float = 120.0,
        **kwargs: Any,
    ) -> None:
        # The google-genai SDK retries 429/5xx itself with long backoffs, which hid a 503 for
        # over a minute in testing. One attempt per request; this class decides what's next.
        kwargs.setdefault("http_options", {"retry_options": {"attempts": 1}})
        # Pipecat's own stream timeout (20 s by default) would cut the last model's longer
        # first-chunk wait short; keep it just above ours so this class decides.
        kwargs.setdefault(
            "stream_idle_timeout_secs", max(last_model_timeout_s, first_chunk_timeout_s) + 5
        )
        super().__init__(**kwargs)
        self._fallback_model = fallback_model
        self._rate_limit_retries = rate_limit_retries
        self._backoff_s = backoff_s
        self._first_chunk_timeout_s = first_chunk_timeout_s
        # With nothing left to switch to, a slow answer beats silence (seen live: 28 s).
        self._last_model_timeout_s = max(last_model_timeout_s, first_chunk_timeout_s)
        self._cooldown_s = cooldown_s
        self.on_model_used: ModelListener | None = None

    async def _stream_response(self, context: LLMContext) -> AsyncIterator[Any]:
        # The base class reads the model from settings when the request is sent, so the
        # model is switched there for the duration of one attempt and restored afterwards.
        primary = str(self._settings.model)
        models = [primary]
        if self._fallback_model and self._fallback_model != primary:
            models.append(self._fallback_model)

        last_error: Exception | None = None
        try:
            for index, model in enumerate(models):
                is_last = index == len(models) - 1
                if not is_last and _cooling_down(model):
                    logger.warning("Gemini %s is cooling down after a failure; skipping", model)
                    continue
                for attempt in range(self._rate_limit_retries + 1):
                    self._settings.model = model
                    async with aclosing(super()._stream_response(context)) as stream:
                        try:
                            wait = (
                                self._last_model_timeout_s
                                if is_last
                                else self._first_chunk_timeout_s
                            )
                            async with asyncio.timeout(wait):
                                first = await anext(stream)
                        except StopAsyncIteration:
                            await self._report_model(model, primary)
                            return
                        except TimeoutError as exc:
                            # Accepted but silent: seen live when the model is under load.
                            logger.warning("Gemini %s sent nothing in time; moving on", model)
                            last_error = exc
                            _start_cooldown(model, self._cooldown_s)
                            break
                        except APIError as exc:
                            if exc.code not in _RETRYABLE | _SWITCH_NOW:
                                raise
                            last_error = exc
                            logger.warning("Gemini %s failed with %s", model, exc.code)
                            if (
                                exc.code in _SWITCH_NOW
                                or _daily_quota_exhausted(exc)
                                or attempt == self._rate_limit_retries
                            ):
                                _start_cooldown(model, self._cooldown_s)
                                break
                            await asyncio.sleep(self._backoff_s * 2**attempt)
                            continue
                        # The request has been sent with `model`; restore the setting before
                        # yielding so a consumer cancelled mid-stream can't leave it switched.
                        self._settings.model = primary
                        await self._report_model(model, primary)
                        yield first
                        async for chunk in stream:
                            yield chunk
                        return
        finally:
            self._settings.model = primary
        # Every model ran out of attempts; surface the last provider error to the pipeline.
        raise last_error or RuntimeError("Gemini returned no response")

    async def _report_model(self, model: str, primary: str) -> None:
        if model != primary:
            logger.warning("Gemini fell back from %s to %s for this turn", primary, model)
        if self.on_model_used is not None:
            await self.on_model_used(model)


# Groq answers these by moving to the fallback model: unknown model, or the service failing.
_GROQ_SWITCH_NOW = {404, 500, 502, 503}
_DURATION_PART = re.compile(r"(\d+(?:\.\d+)?)(ms|h|m|s)")
_UNIT_S = {"ms": 0.001, "s": 1.0, "m": 60.0, "h": 3600.0}


def parse_reset_s(value: str | None) -> float | None:
    """Seconds from a `retry-after` ("7") or `x-ratelimit-reset-*` ("2m59.5s", "120ms")."""
    if not value:
        return None
    value = value.strip()
    try:
        return float(value)
    except ValueError:
        pass
    parts = _DURATION_PART.findall(value)
    if not parts:
        return None
    return sum(float(number) * _UNIT_S[unit] for number, unit in parts)


def rate_limit_wait_s(exc: RateLimitError) -> float | None:
    """How long Groq says to wait. Prefers `retry-after`, then the tokens-per-minute reset
    (the limit voice calls hit first), then the requests reset."""
    headers = exc.response.headers
    for name in ("retry-after", "x-ratelimit-reset-tokens", "x-ratelimit-reset-requests"):
        wait = parse_reset_s(headers.get(name))
        if wait is not None:
            return wait
    return None


class FallbackGroqLLMService(GroqLLMService):
    """Groq (OpenAI-compatible) with one header-timed retry on a 429, then the fallback."""

    def __init__(
        self,
        *,
        fallback_model: str | None,
        max_rate_limit_wait_s: float = 10.0,
        cooldown_s: float = 60.0,
        request_timeout_s: float = 8.0,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        # The openai SDK retries 429/5xx itself (2 retries, own backoff); this class decides.
        # Its default timeout is 10 minutes: live, a hung connection held a turn for 26 s
        # before failing. A short one moves to the fallback while the caller still waits.
        self._client = self._client.with_options(max_retries=0, timeout=request_timeout_s)
        self._fallback_model = fallback_model
        self._max_rate_limit_wait_s = max_rate_limit_wait_s
        self._cooldown_s = cooldown_s
        self.on_model_used: ModelListener | None = None

    async def get_chat_completions(self, context: LLMContext) -> AsyncStream[ChatCompletionChunk]:
        # The request is built from `self._settings.model` when it is sent; `create` returns
        # once the response headers arrive, which is where rate limits and outages surface.
        primary = str(self._settings.model)
        models = [primary]
        if self._fallback_model and self._fallback_model != primary:
            models.append(self._fallback_model)

        last_error: Exception | None = None
        try:
            for index, model in enumerate(models):
                is_last = index == len(models) - 1
                if not is_last and _cooling_down(model):
                    logger.warning("Groq %s is cooling down after a failure; skipping", model)
                    continue
                for attempt in range(2):
                    self._settings.model = model
                    try:
                        stream = await super().get_chat_completions(context)
                    except RateLimitError as exc:
                        last_error = exc
                        wait = rate_limit_wait_s(exc)
                        logger.warning("Groq %s rate limited; reset in %s s", model, wait)
                        if (
                            attempt == 0
                            and wait is not None
                            and wait <= self._max_rate_limit_wait_s
                        ):
                            await asyncio.sleep(wait)
                            continue
                        _start_cooldown(model, wait if wait is not None else self._cooldown_s)
                        break
                    except APIStatusError as exc:
                        if exc.status_code not in _GROQ_SWITCH_NOW:
                            raise
                        last_error = exc
                        logger.warning("Groq %s failed with %s", model, exc.status_code)
                        _start_cooldown(model, self._cooldown_s)
                        break
                    except (APITimeoutError, APIConnectionError) as exc:
                        last_error = exc
                        logger.warning("Groq %s unreachable: %s", model, exc)
                        _start_cooldown(model, self._cooldown_s)
                        break
                    if model != primary:
                        logger.warning("Groq fell back from %s to %s for this turn", primary, model)
                    if self.on_model_used is not None:
                        await self.on_model_used(model)
                    return stream
        finally:
            self._settings.model = primary
        raise last_error or RuntimeError("Groq returned no response")
