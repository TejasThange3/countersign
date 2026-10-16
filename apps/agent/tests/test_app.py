"""The FastAPI app: health, factory loading and the text-mode endpoints (fake LLM + gateway)."""

from __future__ import annotations

import logging
from collections.abc import Iterator
from typing import Any

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
    assert later["messages"] == [
        "Good news: the manager approved it, and your refund of 250 dollars has gone through."
    ]


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


class RecordingDesk:
    """Stands in for the ArmorIQ manager desk: records what it was asked to decide."""

    def __init__(self, ok: bool = True) -> None:
        self.ok = ok
        self.decided: list[tuple[str, str]] = []

    async def decide(self, held: Any, decision: str) -> Any:
        from countersign_agent.bridge.delegation import DelegationDecisionResult

        self.decided.append((held.tool, decision))
        return DelegationDecisionResult(
            decision=decision,  # type: ignore[arg-type]
            status_code=201 if self.ok else 403,
            ok=self.ok,
            body={},
        )


def desk_client(desk: RecordingDesk | None) -> TestClient:
    app = create_app(
        make_settings(hold_timeout_s=30.0),
        FakeGatewayFactory(approval_delay_s=30),
        llm_factory=lambda _s: FakeScriptedLLM(hotel_script),
        manager_desk=desk,
    )
    return TestClient(app)


def test_caller_can_decide_their_own_held_request() -> None:
    desk = RecordingDesk()
    with desk_client(desk) as client:
        call_id = client.post("/text/calls").json()["call_id"]
        client.post(
            f"/text/calls/{call_id}/turns",
            json={"text": "Refund 250 please", "wait_for_holds": False},
        )
        decided = client.post(f"/text/calls/{call_id}/decision", json={"decision": "approve"})
        assert decided.status_code == 200
        assert decided.json() == {
            "tool": "issue_refund",
            "decision": "approve",
            "armoriq_status": 201,
        }
        assert desk.decided == [("issue_refund", "approve")]
        client.delete(f"/text/calls/{call_id}")


def test_decision_without_a_held_request_is_a_conflict() -> None:
    desk = RecordingDesk()
    with desk_client(desk) as client:
        call_id = client.post("/text/calls").json()["call_id"]
        response = client.post(f"/text/calls/{call_id}/decision", json={"decision": "approve"})
        assert response.status_code == 409
        assert desk.decided == []


def test_decision_for_an_unknown_call_is_404() -> None:
    with desk_client(RecordingDesk()) as client:
        response = client.post("/text/calls/nope/decision", json={"decision": "reject"})
        assert response.status_code == 404


def test_decisions_are_off_unless_enabled() -> None:
    with desk_client(None) as client:
        call_id = client.post("/text/calls").json()["call_id"]
        response = client.post(f"/text/calls/{call_id}/decision", json={"decision": "approve"})
        assert response.status_code == 403


def test_armoriq_refusal_is_reported_as_502() -> None:
    with desk_client(RecordingDesk(ok=False)) as client:
        call_id = client.post("/text/calls").json()["call_id"]
        client.post(
            f"/text/calls/{call_id}/turns",
            json={"text": "Refund 250 please", "wait_for_holds": False},
        )
        response = client.post(f"/text/calls/{call_id}/decision", json={"decision": "approve"})
        assert response.status_code == 502
        client.delete(f"/text/calls/{call_id}")


def test_cors_allows_only_the_configured_website() -> None:
    app = create_app(
        make_settings(cors_origins="https://countersign.example, https://preview.example/"),
        FakeGatewayFactory(),
        llm_factory=lambda _s: FakeScriptedLLM(hotel_script),
    )
    with TestClient(app) as client:
        ok = client.options(
            "/text/calls",
            headers={"Origin": "https://preview.example", "Access-Control-Request-Method": "POST"},
        )
        assert ok.headers.get("access-control-allow-origin") == "https://preview.example"
        other = client.get("/health", headers={"Origin": "https://evil.example"})
        assert "access-control-allow-origin" not in other.headers


def test_idle_text_calls_are_hung_up() -> None:
    import time as _time

    factory = FakeGatewayFactory()
    app = create_app(
        make_settings(text_call_idle_s=0.2),
        factory,
        llm_factory=lambda _s: FakeScriptedLLM(hotel_script),
    )
    with TestClient(app) as client:
        call_id = client.post("/text/calls").json()["call_id"]
        _time.sleep(0.6)  # the sweeper runs every idle/2 seconds
        assert client.post(f"/text/calls/{call_id}/collect").status_code == 404
        assert factory.opened[0].closed


def test_open_calls_are_capped() -> None:
    app = create_app(
        make_settings(max_text_calls=1),
        FakeGatewayFactory(),
        llm_factory=lambda _s: FakeScriptedLLM(hotel_script),
    )
    with TestClient(app) as client:
        assert client.post("/text/calls").status_code == 201
        busy = client.post("/text/calls")
        assert busy.status_code == 503


def voice_app(monkeypatch: pytest.MonkeyPatch, **settings: Any) -> tuple[Any, list[Any]]:
    """The app with the audio pipeline replaced: the call registers a core with one held
    request, then waits until the browser hangs up."""
    import asyncio

    from countersign_agent import app as app_module
    from countersign_agent.contracts import Decision, Outcome, ToolResult

    held = ToolResult(
        tool="issue_refund",
        decision=Decision.HOLD,
        outcome=Outcome.PENDING,
        content="pending",
        delegation_id="d-1",
        armoriq_mode="live",
    )

    class Router:
        def __init__(self) -> None:
            self.held_requests = [held]

    class Core:
        def __init__(self) -> None:
            self.router = Router()

    async def fake_call(call_id: str, transport: Any, *_a: Any, on_core: Any, **_k: Any) -> None:
        on_core(Core())
        try:
            await asyncio.sleep(3600)
        finally:
            on_core(None)

    monkeypatch.setattr(app_module, "run_audio_call", fake_call)
    desk = RecordingDesk()
    app = create_app(
        make_settings(**settings),
        FakeGatewayFactory(),
        llm_factory=lambda _s: FakeScriptedLLM(hotel_script),
        manager_desk=desk,
    )
    return app, desk.decided


def test_voice_call_announces_its_id_and_its_hold_can_be_decided(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, decided = voice_app(monkeypatch, cors_origins="https://site.example")
    with TestClient(app) as client:
        with client.websocket_connect("/voice", headers={"origin": "https://site.example"}) as ws:
            first = ws.receive_json()
            assert first["type"] == "call"
            response = client.post(
                f"/calls/{first['call_id']}/decision", json={"decision": "reject"}
            )
            assert response.status_code == 200
    assert decided == [("issue_refund", "reject")]


def test_voice_from_another_origin_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    from starlette.websockets import WebSocketDisconnect

    app, _ = voice_app(monkeypatch, cors_origins="https://site.example")
    with TestClient(app) as client:
        with pytest.raises(WebSocketDisconnect) as closed:
            with client.websocket_connect("/voice", headers={"origin": "https://evil.example"}):
                pass
        assert closed.value.code == 1008


def test_voice_calls_are_capped(monkeypatch: pytest.MonkeyPatch) -> None:
    app, _ = voice_app(monkeypatch, max_voice_calls=1)
    with TestClient(app) as client:
        with client.websocket_connect("/voice") as first:
            assert first.receive_json()["type"] == "call"
            with client.websocket_connect("/voice") as second:
                assert second.receive_json() == {"type": "busy"}


def test_text_call_accepts_the_typed_option() -> None:
    with TestClient(
        create_app(
            make_settings(),
            FakeGatewayFactory(),
            llm_factory=lambda _s: FakeScriptedLLM(hotel_script),
        )
    ) as client:
        assert client.post("/text/calls", json={"typed": True}).status_code == 201
        assert client.post("/text/calls").status_code == 201  # no body: evals, unchanged
