"""decide_delegation against a fake transport (httpx.MockTransport); no ArmorIQ is contacted."""

from __future__ import annotations

import json

import httpx
from armoriq_spike.delegation import ApproverRole, decide_delegation, fetch_approver_role


def fake_backend(status: int, body: object, seen: list[httpx.Request]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(status, json=body)

    return httpx.MockTransport(handler)


async def test_approve_posts_delegation_id_with_given_headers() -> None:
    seen: list[httpx.Request] = []
    async with httpx.AsyncClient(transport=fake_backend(200, {"success": True}, seen)) as http:
        result = await decide_delegation(
            http, "https://fake.backend", "d-1", {"X-API-Key": "fake-key"}, "boss@example.com"
        )
    assert result.ok and result.status_code == 200
    assert seen[0].url == "https://fake.backend/delegation/approve"
    assert json.loads(seen[0].content) == {
        "delegationId": "d-1",
        "approverEmail": "boss@example.com",
    }
    assert seen[0].headers["X-API-Key"] == "fake-key"
    assert seen[0].headers["X-User-Email"] == "boss@example.com"


async def test_reject_uses_reject_route_and_reports_failure() -> None:
    seen: list[httpx.Request] = []
    async with httpx.AsyncClient(transport=fake_backend(403, {"message": "no"}, seen)) as http:
        result = await decide_delegation(
            http, "https://fake.backend", "d-2", {}, "boss@example.com", "reject"
        )
    assert seen[0].url.path == "/delegation/reject"
    assert not result.ok
    assert result.body == {"message": "no"}


async def test_declared_approver_role_and_limit_go_in_the_body() -> None:
    seen: list[httpx.Request] = []
    async with httpx.AsyncClient(transport=fake_backend(200, {}, seen)) as http:
        await decide_delegation(
            http,
            "https://fake.backend",
            "d-3",
            {},
            "boss@example.com",
            approver=ApproverRole(role="org_admin", limit=500),
        )
    body = json.loads(seen[0].content)
    assert body["approverRole"] == "org_admin"
    assert body["approverLimit"] == 500


async def test_reject_never_sends_role_or_limit() -> None:
    seen: list[httpx.Request] = []
    async with httpx.AsyncClient(transport=fake_backend(201, {}, seen)) as http:
        await decide_delegation(
            http,
            "https://fake.backend",
            "d-4",
            {},
            "boss@example.com",
            "reject",
            approver=ApproverRole(role="org_admin", limit=500),
        )
    assert json.loads(seen[0].content) == {
        "delegationId": "d-4",
        "approverEmail": "boss@example.com",
    }


async def test_fetch_approver_role_reads_my_role_for_that_email() -> None:
    seen: list[httpx.Request] = []
    reply = {"role": "org_admin", "limit": 1000000000, "tools": []}
    async with httpx.AsyncClient(transport=fake_backend(200, reply, seen)) as http:
        role = await fetch_approver_role(
            http, "https://fake.backend", {"X-API-Key": "fake-key"}, "boss@example.com"
        )
    assert role == ApproverRole(role="org_admin", limit=1e9)
    assert seen[0].url.path == "/delegation/my-role"
    assert seen[0].headers["X-User-Email"] == "boss@example.com"
