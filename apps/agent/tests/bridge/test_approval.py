"""wait_for_approval against FakeApprovalBackend (a fake ArmorIQClient); no network."""

from __future__ import annotations

import asyncio
import time

import pytest
from armoriq_sdk.exceptions import DelegationException
from countersign_agent.bridge.approval import wait_for_approval


class FakeApprovalBackend:
    """Answers a scripted sequence of statuses (or exceptions); blocks like real HTTP if asked."""

    def __init__(self, statuses: list[str | Exception], block_seconds: float = 0.0) -> None:
        self.statuses = statuses
        self.block_seconds = block_seconds
        self.polls = 0
        self.marked: list[tuple[str, str, str | None]] = []

    def get_delegation_status(self, delegation_id: str) -> str:
        # time.sleep on purpose: this stands in for the SDK's synchronous httpx call.
        time.sleep(self.block_seconds)
        item = self.statuses[min(self.polls, len(self.statuses) - 1)]
        self.polls += 1
        if isinstance(item, Exception):
            raise item
        return item

    def mark_delegation_executed(
        self, user_email: str, delegation_id: str, plan_id: str | None = None
    ) -> None:
        time.sleep(self.block_seconds)
        self.marked.append((user_email, delegation_id, plan_id))


async def wait(backend: FakeApprovalBackend, limit: float = 1.0, interval: float = 0.01) -> str:
    return await wait_for_approval(
        backend,
        "d-1",
        user_email="guest@example.com",
        plan_id="plan-1",
        timeout_seconds=limit,
        interval=interval,
    )


async def test_approved_marks_executed_for_this_plan() -> None:
    backend = FakeApprovalBackend(["pending", "pending", "approved"])
    assert await wait(backend) == "approved"
    assert backend.polls == 3
    assert backend.marked == [("guest@example.com", "d-1", "plan-1")]


async def test_rejected_never_marks_executed() -> None:
    backend = FakeApprovalBackend(["pending", "rejected"])
    assert await wait(backend) == "rejected"
    assert backend.marked == []


async def test_nobody_decides_times_out() -> None:
    backend = FakeApprovalBackend(["pending"])
    assert await wait(backend, limit=0.05) == "timeout"
    assert backend.marked == []


async def test_expired_stops_waiting_early() -> None:
    backend = FakeApprovalBackend(["expired"])
    assert await wait(backend, limit=10) == "timeout"
    assert backend.polls == 1


async def test_transient_error_backs_off_and_keeps_waiting() -> None:
    rate_limited = DelegationException("429", delegation_id="d-1", status_code=429)
    backend = FakeApprovalBackend([rate_limited, "approved"])
    assert await wait(backend) == "approved"
    assert backend.polls == 2


async def test_other_http_error_propagates_so_the_caller_fails_closed() -> None:
    forbidden = DelegationException("403", delegation_id="d-1", status_code=403)
    backend = FakeApprovalBackend([forbidden])
    with pytest.raises(DelegationException):
        await wait(backend)


async def test_event_loop_stays_responsive_while_polls_block() -> None:
    """Each fake poll blocks its thread for 400 ms, like a slow status request. A ticker on
    the event loop must keep ticking: the voice pipeline can't freeze while a manager decides.
    """
    backend = FakeApprovalBackend(["pending", "pending", "approved"], block_seconds=0.4)
    gaps: list[float] = []

    async def ticker() -> None:
        last = time.perf_counter()
        while True:
            await asyncio.sleep(0.01)
            now = time.perf_counter()
            gaps.append(now - last)
            last = now

    tick = asyncio.create_task(ticker())
    try:
        assert await wait(backend, limit=5) == "approved"
    finally:
        tick.cancel()
    # 3 polls + 1 mark at 400 ms each: an on-loop call would leave a gap of >= 400 ms. The 250 ms
    # bound leaves room for a slow Windows CI box while still catching any on-loop call.
    assert len(gaps) > 20
    assert max(gaps) < 0.25


async def test_approval_arriving_after_the_deadline_is_a_timeout() -> None:
    """A slow poll that answers "approved" after the window closed must not authorize the
    tool: the caller already treats the call as timed out (fail closed)."""
    backend = FakeApprovalBackend(["approved"], block_seconds=0.2)
    started = time.perf_counter()
    assert await wait(backend, limit=0.05, interval=0.01) == "timeout"
    assert backend.marked == []
    # The wait itself ends near the deadline, not when the slow poll finally returns.
    assert time.perf_counter() - started < 0.15


async def test_window_includes_network_time() -> None:
    # Each poll takes 30 ms and answers pending: the SDK would keep going for 25 sleeps of
    # 10 ms (~1 s of real time); the deadline stops at about 0.25 s of wall-clock time.
    backend = FakeApprovalBackend(["pending"], block_seconds=0.03)
    started = time.perf_counter()
    assert await wait(backend, limit=0.25, interval=0.01) == "timeout"
    elapsed = time.perf_counter() - started
    assert elapsed < 0.4
    assert backend.polls < 10


async def test_cancelling_the_wait_stops_polling() -> None:
    backend = FakeApprovalBackend(["pending"])
    task = asyncio.create_task(wait(backend, limit=10, interval=0.01))
    await asyncio.sleep(0.05)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    polls_at_cancel = backend.polls
    await asyncio.sleep(0.05)
    assert backend.polls == polls_at_cancel
