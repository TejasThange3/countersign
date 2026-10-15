"""ToolRouter hold behaviour, tested directly and through text mode."""

from __future__ import annotations

import asyncio
from typing import Any

from countersign_agent.contracts import Outcome, ToolResult
from countersign_agent.voice.fake_gateway import FakeGateway, FakeGatewayFactory
from countersign_agent.voice.holds import (
    HOLD_ANNOUNCEMENT,
    PENDING_RESULT,
    ToolRouter,
)
from countersign_agent.voice.text_mode import TextSession
from fakes import FakeScriptedLLM, hotel_script, make_settings


class RecordingOutput:
    """CallOutput fake that logs everything in order."""

    def __init__(self) -> None:
        self.log: list[str] = []
        self.outcomes: list[ToolResult] = []

    async def say(self, text: str) -> None:
        self.log.append(f"say:{text}")

    async def play_filler(self) -> None:
        self.log.append("filler")

    async def deliver_hold_outcome(self, tool: str, result: ToolResult) -> None:
        self.log.append(f"outcome:{tool}:{result.outcome}")
        self.outcomes.append(result)


class FakeParams:
    """Stands in for pipecat's FunctionCallParams: name, arguments and result_callback."""

    def __init__(self, name: str, arguments: dict[str, Any], log: list[str]) -> None:
        self.function_name = name
        self.arguments = arguments
        self.results: list[tuple[Any, Any]] = []
        self._log = log

    async def result_callback(self, result: Any, *, properties: Any = None) -> None:
        self._log.append("result")
        self.results.append((result, properties))


def make_router(gateway: FakeGateway, output: RecordingOutput) -> ToolRouter:
    return ToolRouter(gateway, output, hold_timeout_s=5.0, filler_interval_s=0.02)


REFUND_250 = {"booking_id": 1001, "amount": 250.0, "reason": "noise"}


async def test_hold_speaks_first_and_waits_in_background() -> None:
    gateway = FakeGateway("c1", approval_delay_s=30)
    output = RecordingOutput()
    router = make_router(gateway, output)
    params = FakeParams("issue_refund", REFUND_250, output.log)

    # The handler must return promptly even though the approver has not answered.
    await asyncio.wait_for(router.handle(params), timeout=1)  # type: ignore[arg-type]

    assert output.log[:2] == [f"say:{HOLD_ANNOUNCEMENT}", "result"]
    result, properties = params.results[0]
    assert result == PENDING_RESULT
    assert properties.run_llm is False  # the LLM must not talk over the announcement
    assert router.pending_tools == ["issue_refund"]

    await asyncio.sleep(0.1)
    assert "filler" in output.log  # filler plays while waiting

    gateway.release()
    await router.wait_for_holds()
    assert output.log[-1] == "outcome:issue_refund:ran"
    assert router.pending_tools == []


async def test_repeat_call_during_hold_never_reaches_gateway() -> None:
    gateway = FakeGateway("c1", approval_delay_s=30)
    output = RecordingOutput()
    router = make_router(gateway, output)
    await router.handle(FakeParams("issue_refund", REFUND_250, output.log))  # type: ignore[arg-type]

    # Same tool, differently formatted arguments: still the same pending request.
    again = FakeParams("issue_refund", {"booking_id": 1001, "amount": 250, "reason": "x"}, [])
    await router.handle(again)  # type: ignore[arg-type]

    assert len(gateway.calls) == 1
    assert "STILL_WAITING" in again.results[0][0]
    await router.close()


async def test_hangup_cancels_the_wait() -> None:
    gateway = FakeGateway("c1", approval_delay_s=30)
    output = RecordingOutput()
    router = make_router(gateway, output)
    await router.handle(FakeParams("issue_refund", REFUND_250, output.log))  # type: ignore[arg-type]
    await asyncio.sleep(0.05)

    await router.close()

    assert gateway.waits_started == 1
    assert gateway.waits_cancelled == 1
    assert output.outcomes == []  # nothing is delivered after hangup
    assert router.pending_tools == []


async def test_wait_error_fails_closed() -> None:
    class BrokenWait(FakeGateway):
        async def wait(self, held: ToolResult, timeout_s: float = 60.0) -> ToolResult:
            raise RuntimeError("delegation API down")

    output = RecordingOutput()
    router = make_router(BrokenWait("c1"), output)
    await router.handle(FakeParams("issue_refund", REFUND_250, output.log))  # type: ignore[arg-type]
    await router.wait_for_holds()

    assert output.outcomes[0].outcome is Outcome.NOT_RUN
    assert output.outcomes[0].reason == "hold_wait_error"


async def test_barge_in_during_hold_in_text_mode() -> None:
    factory = FakeGatewayFactory(approval_delay_s=30)
    llm = FakeScriptedLLM(hotel_script)
    session = await TextSession.open("barge", factory, make_settings(), llm_factory=lambda _s: llm)
    try:
        first = await session.send("Please refund 250 dollars", wait_for_holds=False)
        assert first.messages == [HOLD_ANNOUNCEMENT]
        assert first.pending_holds == ["issue_refund"]

        # The caller talks over the hold and asks again; the LLM tries the tool again.
        second = await session.send("Hello? I want my 250 refund", wait_for_holds=False)
        assert second.messages == ["I'm still waiting on the manager, thanks for your patience."]
        assert len(factory.opened[0].calls) == 1

        factory.opened[0].release()
        final = await session.collect()
        assert final.messages == ["Good news, the manager approved it and it's done."]
    finally:
        await session.close()


async def test_hangup_in_text_mode_cancels_wait_and_closes_gateway() -> None:
    factory = FakeGatewayFactory(approval_delay_s=30)
    llm = FakeScriptedLLM(hotel_script)
    session = await TextSession.open("hangup", factory, make_settings(), llm_factory=lambda _s: llm)
    await session.send("Please refund 250 dollars", wait_for_holds=False)
    await session.close()

    gateway = factory.opened[0]
    assert gateway.waits_cancelled == 1
    assert gateway.closed
