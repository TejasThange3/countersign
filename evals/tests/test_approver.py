"""Approver tests over a fake HTTP transport. No real ArmorIQ calls."""

from __future__ import annotations

import json

import httpx
import pytest
from countersign_evals.approver import (
    Approver,
    ApproverConfigError,
    ApproverSettings,
    RatePacer,
    load_approver_settings,
)
from fakes import FakeDelegationApi
from pydantic import SecretStr

SETTINGS = ApproverSettings(
    armoriq_api_key=SecretStr("ak_live_fake"),
    armoriq_admin_email="manager@example.com",
    armoriq_backend_endpoint="https://fake.armoriq.test",
)


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


def _approver(api: FakeDelegationApi, pacer: RatePacer | None = None) -> Approver:
    http = httpx.AsyncClient(transport=httpx.MockTransport(api))
    clock = FakeClock()
    return Approver(http, SETTINGS, pacer or RatePacer(60, clock=clock, sleep=clock.sleep))


async def test_approve_sends_the_role_and_limit_read_from_my_role() -> None:
    api = FakeDelegationApi(role="frontdesk-manager", limit=500)
    result = await _approver(api).decide("del-1", "approve")

    assert result.ok and result.status_code == 201 and result.delegation_id == "del-1"
    role_req, approve_req = api.requests
    assert role_req.url.path == "/delegation/my-role"
    assert role_req.headers["X-User-Email"] == "manager@example.com"
    assert approve_req.url.path == "/delegation/approve"
    assert approve_req.headers["X-API-Key"] == "ak_live_fake"
    assert approve_req.headers["X-User-Email"] == "manager@example.com"
    assert json.loads(approve_req.content) == {
        "delegationId": "del-1",
        "approverEmail": "manager@example.com",
        "approverRole": "frontdesk-manager",
        "approverLimit": 500.0,
    }


async def test_reject_never_sends_role_or_limit() -> None:
    api = FakeDelegationApi()
    result = await _approver(api).decide("del-2", "reject")

    assert result.ok
    (reject_req,) = api.requests  # no my-role lookup needed for a reject
    assert reject_req.url.path == "/delegation/reject"
    assert json.loads(reject_req.content) == {
        "delegationId": "del-2",
        "approverEmail": "manager@example.com",
    }


async def test_role_is_looked_up_once_per_run() -> None:
    api = FakeDelegationApi()
    approver = _approver(api)
    await approver.decide("a", "approve")
    await approver.decide("b", "approve")
    assert [r.url.path for r in api.requests].count("/delegation/my-role") == 1


async def test_a_refused_decision_is_reported_not_raised() -> None:
    api = FakeDelegationApi()
    api.fail_with = 403
    result = await _approver(api).decide("del-3", "approve")
    assert not result.ok and result.status_code == 403
    assert result.body == {"message": "fake failure"}


async def test_my_role_failure_raises() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"message": "bad key"})

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    with pytest.raises(httpx.HTTPStatusError):
        await Approver(http, SETTINGS).decide("x", "approve")


async def test_pacer_spaces_calls_under_the_rate_limit() -> None:
    clock = FakeClock()
    pacer = RatePacer(30, clock=clock, sleep=clock.sleep)  # one call every 2 s
    for _ in range(4):
        await pacer.wait()
    assert clock.sleeps == [2.0, 2.0, 2.0]


async def test_pacer_does_not_sleep_when_calls_are_already_spaced() -> None:
    clock = FakeClock()
    pacer = RatePacer(30, clock=clock, sleep=clock.sleep)
    await pacer.wait()
    clock.now += 5
    await pacer.wait()
    assert clock.sleeps == []


async def test_approver_requests_go_through_the_pacer() -> None:
    clock = FakeClock()
    api = FakeDelegationApi()
    approver = _approver(api, RatePacer(30, clock=clock, sleep=clock.sleep))
    await approver.decide("a", "approve")  # my-role + approve
    await approver.decide("b", "reject")
    assert clock.sleeps == [2.0, 2.0]


def test_pacer_rejects_a_non_positive_rate() -> None:
    with pytest.raises(ValueError, match="positive"):
        RatePacer(0)


def test_settings_refuse_to_load_in_ci(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CI", "true")
    with pytest.raises(ApproverConfigError, match="never runs in CI"):
        load_approver_settings()


def test_settings_require_key_and_email(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.setenv("ARMORIQ_API_KEY", "")
    monkeypatch.setenv("ARMORIQ_ADMIN_EMAIL", "")
    with pytest.raises(ApproverConfigError, match="ARMORIQ_API_KEY, ARMORIQ_ADMIN_EMAIL"):
        load_approver_settings()


def test_settings_cap_the_rate_at_60_per_minute() -> None:
    with pytest.raises(ValueError, match="60"):
        ApproverSettings(approver_calls_per_minute=120)
