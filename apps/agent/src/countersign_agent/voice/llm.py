"""Gemini with backoff on rate limits and a recorded, never-silent fallback model.

The free Gemini tier rate-limits often. On a 429 or 5xx we back off and retry the same
model a few times, then move to the fallback model. Retrying is only safe before the first
chunk has been streamed, which is where these errors surface. Every inference reports the
model that actually answered through `on_model_used`, and a fallback is logged as a warning,
so evals can say which model produced each turn.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import aclosing
from typing import Any

from google.genai.errors import APIError
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.services.google.llm import GoogleLLMService

logger = logging.getLogger(__name__)

ModelListener = Callable[[str], Awaitable[None]]

# Worth retrying on the same model after a backoff: rate limited.
_RETRYABLE = {429}
# Worth moving straight to the fallback: model unknown to this key (404), or overloaded /
# erroring (500, 503 "high demand", seen live on the free tier). Retrying those only adds
# seconds of silence on a phone call.
_SWITCH_NOW = {404, 500, 503}


# A model that just failed is skipped (unless it is the last option) for this long, so an
# overloaded primary doesn't add seconds of silence to every turn. Process-wide on purpose:
# one LLM instance exists per call, and the overload outlives any single call.
_cooldown_until: dict[str, float] = {}


def _cooling_down(model: str) -> bool:
    return time.monotonic() < _cooldown_until.get(model, 0.0)


def _start_cooldown(model: str, seconds: float) -> None:
    if seconds <= 0:
        return
    logger.warning("Gemini %s skipped for the next %.0fs after a failure", model, seconds)
    _cooldown_until[model] = time.monotonic() + seconds


class FallbackGoogleLLMService(GoogleLLMService):
    def __init__(
        self,
        *,
        fallback_model: str | None,
        rate_limit_retries: int = 2,
        backoff_s: float = 2.0,
        first_chunk_timeout_s: float = 10.0,
        cooldown_s: float = 120.0,
        **kwargs: Any,
    ) -> None:
        # The google-genai SDK retries 429/5xx itself with long backoffs, which hid a 503 for
        # over a minute in testing. One attempt per request; this class decides what's next.
        kwargs.setdefault("http_options", {"retry_options": {"attempts": 1}})
        super().__init__(**kwargs)
        self._fallback_model = fallback_model
        self._rate_limit_retries = rate_limit_retries
        self._backoff_s = backoff_s
        self._first_chunk_timeout_s = first_chunk_timeout_s
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
                            async with asyncio.timeout(self._first_chunk_timeout_s):
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
                            if exc.code in _SWITCH_NOW or attempt == self._rate_limit_retries:
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
