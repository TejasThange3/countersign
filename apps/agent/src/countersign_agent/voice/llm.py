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
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import aclosing
from typing import Any

from google.genai.errors import APIError
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.services.google.llm import GoogleLLMService

logger = logging.getLogger(__name__)

ModelListener = Callable[[str], Awaitable[None]]

# Worth retrying on the same model: rate limited, or the service is briefly unavailable.
_RETRYABLE = {429, 500, 503}
# Worth moving straight to the fallback: the model id is unknown to this API key.
_SWITCH_NOW = {404}


class FallbackGoogleLLMService(GoogleLLMService):
    def __init__(
        self,
        *,
        fallback_model: str | None,
        rate_limit_retries: int = 2,
        backoff_s: float = 2.0,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._fallback_model = fallback_model
        self._rate_limit_retries = rate_limit_retries
        self._backoff_s = backoff_s
        self.on_model_used: ModelListener | None = None

    async def _stream_response(self, context: LLMContext) -> AsyncIterator[Any]:
        # The base class reads the model from settings when the request is sent, so the
        # model is switched there for the duration of one attempt and restored afterwards.
        primary = str(self._settings.model)
        models = [primary]
        if self._fallback_model and self._fallback_model != primary:
            models.append(self._fallback_model)

        last_error: APIError | None = None
        try:
            for model in models:
                for attempt in range(self._rate_limit_retries + 1):
                    self._settings.model = model
                    async with aclosing(super()._stream_response(context)) as stream:
                        try:
                            first = await anext(stream)
                        except StopAsyncIteration:
                            await self._report_model(model, primary)
                            return
                        except APIError as exc:
                            if exc.code not in _RETRYABLE | _SWITCH_NOW:
                                raise
                            last_error = exc
                            logger.warning("Gemini %s failed with %s", model, exc.code)
                            if exc.code in _SWITCH_NOW or attempt == self._rate_limit_retries:
                                break
                            await asyncio.sleep(self._backoff_s * 2**attempt)
                            continue
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
