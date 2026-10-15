"""Spacing for delegation API calls, which ArmorIQ rate limits at roughly 30-60 per minute."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable


class RatePacer:
    """Lets at most `per_minute` calls start per minute by spacing them evenly.

    Even spacing (not a burst bucket) because the limit is shared with the bridge's own
    approval polling, and bursts are what trip a rate limiter.
    """

    def __init__(
        self,
        per_minute: float = 30.0,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        if per_minute <= 0:
            raise ValueError("per_minute must be positive")
        self.interval = 60.0 / per_minute
        self._clock = clock
        self._sleep = sleep
        self._next_at: float | None = None
        self._lock = asyncio.Lock()

    async def wait(self) -> None:
        async with self._lock:
            now = self._clock()
            if self._next_at is not None and now < self._next_at:
                await self._sleep(self._next_at - now)
                now = self._next_at
            self._next_at = now + self.interval
