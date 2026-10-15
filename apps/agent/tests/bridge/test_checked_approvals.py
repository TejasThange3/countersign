"""Mark-executed must fail closed. Real ArmorIQClient (SDK 0.6.10) over a fake HTTP transport
(httpx.MockTransport); no network, fake key."""

from __future__ import annotations

import json
from collections.abc import Callable

import httpx
import pytest
from armoriq_sdk import ArmorIQClient
from armoriq_sdk.exceptions import DelegationException
from countersign_agent.bridge.approval import CheckedApprovals
from countersign_agent.contracts import Decision, Outcome

from .fakes import Harness

Handler = Callable[[httpx.Request], httpx.Response]


@pytest.fixture(autouse=True)
def no_retry_sleeps(monkeypatch: pytest.MonkeyPatch) -> None:
    # The SDK's _retry_post sleeps 1-4 s between attempts; tests don't need to wait.
    monkeypatch.setattr("armoriq_sdk.client.time.sleep", lambda _s: None)


def fake_client(handler: Handler, seen: list[httpx.Request]) -> ArmorIQClient:
    def record(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    client = ArmorIQClient(api_key="ak_test_fakefakefake", _skip_api_key_validation=True)
    client.http_client = httpx.Client(transport=httpx.MockTransport(record))
    return client


def mark_returns(status: int) -> Handler:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/status"):
            return httpx.Response(200, json={"status": "approved"})
        return httpx.Response(status, json={"message": f"fake {status}"})

    return handler


def test_sdk_mark_executed_swallows_a_refusal() -> None:
    """Why CheckedApprovals exists. If this starts failing, the SDK fixed it upstream."""
    seen: list[httpx.Request] = []
    client = fake_client(mark_returns(403), seen)
    client.mark_delegation_executed("g@example.com", "d-1", "plan-1")  # no exception
    assert seen[0].url.path == "/delegation/mark-executed"


def test_checked_mark_sends_the_sdk_request() -> None:
    seen: list[httpx.Request] = []
    CheckedApprovals(fake_client(mark_returns(200), seen)).mark_delegation_executed(
        "g@example.com", "d-1", "plan-1"
    )
    request = seen[0]
    assert request.url.path == "/delegation/mark-executed"
    assert json.loads(request.content) == {"delegationId": "d-1", "planId": "plan-1"}
    assert request.headers["X-User-Email"] == "g@example.com"
    assert request.headers["Idempotency-Key"] == "mark-exec:d-1"


def test_checked_mark_raises_on_refusal() -> None:
    seen: list[httpx.Request] = []
    approvals = CheckedApprovals(fake_client(mark_returns(403), seen))
    with pytest.raises(DelegationException) as exc:
        approvals.mark_delegation_executed("g@example.com", "d-1", "plan-1")
    assert exc.value.status_code == 403
    assert len(seen) == 1  # 4xx is not retried


def test_checked_mark_raises_after_retries_are_exhausted() -> None:
    seen: list[httpx.Request] = []
    client = fake_client(mark_returns(503), seen)
    with pytest.raises(DelegationException) as exc:
        CheckedApprovals(client).mark_delegation_executed("g@example.com", "d-1", None)
    assert exc.value.status_code == 503
    assert len(seen) == client.max_retries + 1


def test_checked_mark_propagates_a_network_error_after_retries() -> None:
    def unreachable(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("fake: backend unreachable", request=request)

    seen: list[httpx.Request] = []
    client = fake_client(unreachable, seen)
    with pytest.raises(httpx.ConnectError):
        CheckedApprovals(client).mark_delegation_executed("g@example.com", "d-1", None)
    assert len(seen) == client.max_retries + 1


@pytest.mark.parametrize("mark_status", [403, 503])
async def test_refused_mark_executed_means_the_tool_never_runs(mark_status: int) -> None:
    """End to end through the gateway: approved, but the backend refuses to record the
    approval as used, so the refund must not be issued."""
    approvals = CheckedApprovals(fake_client(mark_returns(mark_status), []))
    h = Harness(approvals=approvals)  # type: ignore[arg-type]  # real client, not FakeApprovals
    gw = await h.open()
    await gw.call("verify_guest", {"booking_ref": "LRK-1001", "last_name": "Okafor"})
    held = await gw.call("issue_refund", {"booking_id": 1, "amount": 250, "reason": "test"})
    assert held.outcome is Outcome.PENDING
    result = await gw.wait(held, timeout_s=5)
    assert result.decision is Decision.UNAVAILABLE
    assert result.outcome is Outcome.NOT_RUN
    assert all(name != "issue_refund" for name, _ in h.mcp.calls)
    assert all(tool != "issue_refund" for tool, _ in h.log.reports)
