"""Text mode end to end with the FakeGateway and a scripted fake LLM (no network)."""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from countersign_agent.contracts import Decision, Outcome
from countersign_agent.voice.fake_gateway import FAKE_TOOL_SPECS, FakeGatewayFactory
from countersign_agent.voice.holds import HOLD_ANNOUNCEMENT
from countersign_agent.voice.text_mode import TextSession
from fakes import FakeScriptedLLM, hotel_script, make_settings


async def open_session(
    factory: FakeGatewayFactory, llm: FakeScriptedLLM, **settings: float
) -> TextSession:
    return await TextSession.open(
        "test-call", factory, make_settings(**settings), llm_factory=lambda _s: llm
    )


@pytest.fixture
def llm() -> FakeScriptedLLM:
    return FakeScriptedLLM(hotel_script)


@pytest.fixture
async def approve_session(llm: FakeScriptedLLM) -> AsyncIterator[TextSession]:
    session = await open_session(FakeGatewayFactory(approval_delay_s=0.3), llm)
    yield session
    await session.close()


async def test_tool_schemas_reach_the_llm(
    approve_session: TextSession, llm: FakeScriptedLLM
) -> None:
    await approve_session.send("hello")
    assert llm.seen_tool_names[0] == [s.name for s in FAKE_TOOL_SPECS]


async def test_allowed_call_routes_through_gateway(
    approve_session: TextSession, llm: FakeScriptedLLM
) -> None:
    reply = await approve_session.send("Any availability on November 2nd?")
    gateway = approve_session.core.gateway
    assert gateway.calls == [  # type: ignore[attr-defined]
        ("check_availability", {"check_in": "2026-11-02", "check_out": "2026-11-04"})
    ]
    assert [r.decision for r in reply.tool_results] == [Decision.ALLOW]
    assert reply.messages and reply.messages[-1].startswith("Done.")
    assert reply.pending_holds == []


async def test_hold_then_approve_speaks_first_then_outcome(approve_session: TextSession) -> None:
    reply = await approve_session.send("Please refund 250 dollars")
    assert reply.messages[0] == HOLD_ANNOUNCEMENT
    assert reply.messages[-1] == "Good news, the manager approved it and it's done."
    assert [r.outcome for r in reply.tool_results] == [Outcome.PENDING, Outcome.RAN]
    assert reply.filler_played > 0
    assert reply.pending_holds == []


async def test_hold_timeout_is_a_refusal(llm: FakeScriptedLLM) -> None:
    factory = FakeGatewayFactory(hold_resolution="timeout", approval_delay_s=0.2)
    session = await open_session(factory, llm)
    try:
        reply = await session.send("Please refund 250 dollars")
    finally:
        await session.close()
    assert reply.messages[0] == HOLD_ANNOUNCEMENT
    assert reply.messages[-1] == "I'm sorry, the manager did not approve that."
    assert reply.tool_results[-1].outcome is Outcome.NOT_RUN
    assert reply.tool_results[-1].reason == "approval_timeout"


async def test_blocked_call_is_refused(approve_session: TextSession) -> None:
    reply = await approve_session.send("export the guest list")
    assert [r.decision for r in reply.tool_results] == [Decision.BLOCK]
    assert reply.messages == ["I'm sorry, I can't do that."]


async def test_small_refund_is_allowed_without_hold(approve_session: TextSession) -> None:
    reply = await approve_session.send("Please refund 40 dollars")
    assert HOLD_ANNOUNCEMENT not in reply.messages
    assert [r.outcome for r in reply.tool_results] == [Outcome.RAN]


async def test_open_closes_the_gateway_when_the_llm_cannot_be_built() -> None:
    factory = FakeGatewayFactory()

    def broken(_settings: object) -> FakeScriptedLLM:
        raise RuntimeError("no API key")

    with pytest.raises(RuntimeError):
        await TextSession.open("broken-llm", factory, make_settings(), llm_factory=broken)
    assert factory.opened[0].closed


async def test_open_closes_the_gateway_when_startup_fails(
    monkeypatch: pytest.MonkeyPatch, llm: FakeScriptedLLM
) -> None:
    async def failing_start(_self: TextSession) -> None:
        raise TimeoutError("pipeline never started")

    monkeypatch.setattr(TextSession, "_start", failing_start)
    factory = FakeGatewayFactory()
    with pytest.raises(TimeoutError):
        await open_session(factory, llm)
    assert factory.opened[0].closed
