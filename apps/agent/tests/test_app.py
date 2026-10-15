"""The FastAPI app: health, factory loading and the text-mode endpoints (fake LLM + gateway)."""

from __future__ import annotations

import logging
from collections.abc import Iterator

import pytest
from countersign_agent.app import create_app, load_factory
from countersign_agent.voice.fake_gateway import FakeGatewayFactory
from countersign_agent.voice.holds import HOLD_ANNOUNCEMENT
from fakes import FakeScriptedLLM, hotel_script, make_settings  # on sys.path via conftest.py
from fastapi.testclient import TestClient


@pytest.fixture
def factory() -> FakeGatewayFactory:
    return FakeGatewayFactory(approval_delay_s=0.2)


@pytest.fixture
def client(factory: FakeGatewayFactory) -> Iterator[TestClient]:
    app = create_app(make_settings(), factory, llm_factory=lambda _s: FakeScriptedLLM(hotel_script))
    with TestClient(app) as test_client:
        yield test_client


def test_health_is_200(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_text_call_round_trip(client: TestClient, factory: FakeGatewayFactory) -> None:
    call_id = client.post("/text/calls").json()["call_id"]

    reply = client.post(f"/text/calls/{call_id}/turns", json={"text": "Refund 250 please"})
    assert reply.status_code == 200
    body = reply.json()
    assert body["messages"][0] == HOLD_ANNOUNCEMENT
    assert [r["outcome"] for r in body["tool_results"]] == ["pending", "ran"]
    assert body["metrics"]["turn"] == 1

    assert client.delete(f"/text/calls/{call_id}").status_code == 204
    assert factory.opened[0].closed
    assert client.post(f"/text/calls/{call_id}/turns", json={"text": "hi"}).status_code == 404


def test_hold_outcome_can_be_collected_later(client: TestClient) -> None:
    call_id = client.post("/text/calls").json()["call_id"]
    first = client.post(
        f"/text/calls/{call_id}/turns",
        json={"text": "Refund 250 please", "wait_for_holds": False},
    ).json()
    assert first["pending_holds"] == ["issue_refund"]

    later = client.post(f"/text/calls/{call_id}/collect").json()
    assert later["pending_holds"] == []
    assert later["messages"] == ["Good news, the manager approved it and it's done."]


def test_empty_turn_is_rejected(client: TestClient) -> None:
    call_id = client.post("/text/calls").json()["call_id"]
    assert client.post(f"/text/calls/{call_id}/turns", json={"text": ""}).status_code == 422


def test_load_factory_warns_loudly_for_the_fake(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING):
        loaded = load_factory("countersign_agent.voice.fake_gateway:factory")
    assert isinstance(loaded, FakeGatewayFactory)
    assert "FAKE GATEWAY IN USE" in caplog.text


def test_load_factory_accepts_a_callable() -> None:
    loaded = load_factory("countersign_agent.voice.fake_gateway:FakeGatewayFactory")
    assert isinstance(loaded, FakeGatewayFactory)


@pytest.mark.parametrize("path", ["no_colon_here", "countersign_agent.voice.config:AgentSettings"])
def test_load_factory_rejects_bad_paths(path: str) -> None:
    with pytest.raises((ValueError, TypeError)):
        load_factory(path)
