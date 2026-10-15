"""Wait for a held call's approval without blocking the event loop.

The SDK's `ArmorIQSession.await_approval` (session.py:1294-1338, v0.6.10) is declared async
but calls the synchronous, network-bound `client.get_delegation_status` and
`client.mark_delegation_executed` directly on the event loop, so every poll freezes the loop
for a full HTTP round trip (and `mark_delegation_executed` retries with its own sleeps). In the
voice pipeline that would stall audio while a manager decides. This copies the SDK's loop
(with a stricter deadline, see wait_for_approval) but runs each network call in a worker
thread. The sleeps stay on the loop, so a cancelled wait (caller hung up) stops polling at once.
"""

from __future__ import annotations

import asyncio
from typing import Literal, Protocol

from armoriq_sdk import ArmorIQClient
from armoriq_sdk.exceptions import DelegationException

ApprovalOutcome = Literal["approved", "rejected", "timeout"]

# Same set as the SDK: rate limits and gateway errors are not a decision, keep waiting.
TRANSIENT_STATUS = frozenset({429, 502, 503, 504})


class ApprovalBackend(Protocol):
    """The two ArmorIQClient methods the wait needs (both blocking HTTP)."""

    def get_delegation_status(self, delegation_id: str) -> str: ...

    def mark_delegation_executed(
        self, user_email: str, delegation_id: str, plan_id: str | None = None
    ) -> None: ...


class CheckedApprovals:
    """ApprovalBackend over a real ArmorIQClient that fails closed on mark-executed refusals.

    The SDK's `mark_delegation_executed` (client.py:1617-1637, v0.6.10) posts through
    `_retry_post`, which returns the last response even when it is a 4xx or a 5xx left after
    retries ran out, and the SDK never checks it. A refused or failed "mark executed" would
    then still let the tool run. This sends the same request (same retry and Idempotency-Key,
    via the pinned SDK's `_retry_post`) and raises unless the backend answered 2xx.
    """

    def __init__(self, client: ArmorIQClient) -> None:
        self.client = client

    def get_delegation_status(self, delegation_id: str) -> str:
        return self.client.get_delegation_status(delegation_id)

    def mark_delegation_executed(
        self, user_email: str, delegation_id: str, plan_id: str | None = None
    ) -> None:
        body: dict[str, str] = {"delegationId": delegation_id}
        if plan_id:
            body["planId"] = plan_id
        response = self.client._retry_post(
            f"{self.client.backend_endpoint}/delegation/mark-executed",
            json=body,
            headers={"X-API-Key": self.client.api_key, "X-User-Email": user_email},
            idempotency_key=f"mark-exec:{delegation_id}",
        )
        if not response.is_success:
            raise DelegationException(
                f"mark-executed refused (HTTP {response.status_code})",
                delegation_id=delegation_id,
                status_code=response.status_code,
            )


async def wait_for_approval(
    backend: ApprovalBackend,
    delegation_id: str,
    *,
    user_email: str,
    plan_id: str | None,
    timeout_seconds: float,
    interval: float,
) -> ApprovalOutcome:
    """Poll until approved / rejected, or until `timeout_seconds` of wall-clock time has passed.

    Mirrors the SDK: sleep first, then poll; transient HTTP errors back off
    (min(2 * interval, 15 s)) and keep waiting; any other error propagates so the caller fails
    closed; on approval the delegation is marked executed for this plan.

    Two deviations, both stricter than the SDK:
    - The window is a monotonic deadline that includes network time (the SDK counts only its
      sleeps, so slow polls stretch the window). Every sleep and poll is bounded by the time
      left, and an approval that arrives after the deadline is treated as a timeout: a late
      "yes" must never let the tool run after the caller was told it timed out.
    - An `expired` delegation ends the wait at once (the SDK keeps polling it).

    The deadline governs when the *decision* must arrive. Marking an in-time approval as
    executed is bookkeeping for that same approval, so it is not cut off at the deadline (its
    own retries can make the return a little late); a failure there propagates and the caller
    fails closed.
    """
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout_seconds

    def remaining() -> float:
        return deadline - loop.time()

    while remaining() > 0:
        await asyncio.sleep(min(interval, remaining()))
        if remaining() <= 0:
            break
        try:
            # The poll thread can't be killed, but the wait stops at the deadline and any
            # answer it gives later is dropped.
            status = await asyncio.wait_for(
                asyncio.to_thread(backend.get_delegation_status, delegation_id),
                timeout=remaining(),
            )
        except TimeoutError:
            break
        except DelegationException as exc:
            if exc.status_code in TRANSIENT_STATUS:
                await asyncio.sleep(max(0.0, min(interval * 2, 15.0, remaining())))
                continue
            raise
        if remaining() <= 0:
            break  # the answer arrived too late to act on
        if status == "approved":
            await asyncio.to_thread(
                backend.mark_delegation_executed, user_email, delegation_id, plan_id
            )
            return "approved"
        if status == "rejected":
            return "rejected"
        if status == "expired":
            return "timeout"
    return "timeout"
