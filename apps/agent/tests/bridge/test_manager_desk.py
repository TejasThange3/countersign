"""The demo manager desk against a fake ArmorIQ backend (httpx.MockTransport)."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
from countersign_agent.bridge import manager_desk
from countersign_agent.bridge.manager_desk import ArmorIQManagerDesk
from countersign_agent.contracts import Decision, Outcome, ToolResult

HELD = ToolResult(
    tool="issue_refund",
    decision=Decision.HOLD,
    outcome=Outcome.PENDING,
    content="pending",
    reason="rule_action_hold",
    delegation_id="d-42",
    armoriq_mode="live",
)


@pytest.fixture
def seen(monkeypatch: pytest.MonkeyPatch) -> list[httpx.Request]:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/delegation/my-role":
            return httpx.Response(200, json={"role": "org_admin", "limit": 1000})
        return httpx.Response(201, json={"success": True})

    real = httpx.AsyncClient

    def client(*args: Any, **kwargs: Any) -> httpx.AsyncClient:
        return real(transport=httpx.MockTransport(handler))

    monkeypatch.setattr(manager_desk.httpx, "AsyncClient", client)
    return requests


async def test_approve_reads_the_real_role_then_approves_the_held_delegation(
    seen: list[httpx.Request],
) -> None:
    desk = ArmorIQManagerDesk("fake-key", "boss@example.com", "https://fake.backend/")
    result = await desk.decide(HELD, "approve")

    assert result.ok
    assert [r.url.path for r in seen] == ["/delegation/my-role", "/delegation/approve"]
    body = json.loads(seen[1].content)
    assert body["delegationId"] == "d-42"
    assert (body["approverRole"], body["approverLimit"]) == ("org_admin", 1000)


async def test_reject_sends_no_role(seen: list[httpx.Request]) -> None:
    desk = ArmorIQManagerDesk("fake-key", "boss@example.com", "https://fake.backend")
    await desk.decide(HELD, "reject")

    assert [r.url.path for r in seen] == ["/delegation/reject"]
    assert "approverRole" not in json.loads(seen[0].content)


async def test_held_result_without_delegation_is_refused() -> None:
    desk = ArmorIQManagerDesk("fake-key", "boss@example.com", "https://fake.backend")
    with pytest.raises(ValueError, match="no delegation id"):
        await desk.decide(HELD.model_copy(update={"delegation_id": None}), "approve")


def test_desk_needs_credentials() -> None:
    with pytest.raises(ValueError, match="ARMORIQ_ADMIN_EMAIL"):
        ArmorIQManagerDesk("fake-key", "", "https://fake.backend")
