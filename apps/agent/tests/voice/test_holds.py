"""ToolRouter hold behaviour, tested directly and through text mode."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from countersign_agent.contracts import Decision, Outcome, ToolResult
from countersign_agent.voice.fake_gateway import FakeGateway, FakeGatewayFactory
from countersign_agent.voice.holds import (
    HOLD_ANNOUNCEMENT,
    PENDING_RESULT,
    ToolRouter,
    hold_outcome_message,
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

    async def deliver_hold_outcome(
        self, tool: str, result: ToolResult, *, interrupted: bool = False
    ) -> None:
        self.log.append(f"{'late' if interrupted else 'outcome'}:{tool}:{result.outcome}")
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


class SlowCall(FakeGateway):
    """gateway.call takes a moment, so two concurrent handlers overlap."""

    async def call(self, name: str, arguments: dict[str, Any]) -> ToolResult:
        await asyncio.sleep(0.05)
        return await super().call(name, arguments)


async def test_same_acting_tool_twice_at_once_reaches_gateway_once() -> None:
    gateway = SlowCall("c1", approval_delay_s=30)
    output = RecordingOutput()
    router = make_router(gateway, output)
    first = FakeParams("issue_refund", REFUND_250, output.log)
    second = FakeParams("issue_refund", dict(REFUND_250), [])

    await asyncio.gather(router.handle(first), router.handle(second))  # type: ignore[arg-type]

    assert len(gateway.calls) == 1
    assert "DUPLICATE" in second.results[0][0]
    await router.close()


async def test_parallel_reads_are_not_deduplicated() -> None:
    gateway = SlowCall("c1")
    router = make_router(gateway, RecordingOutput())
    a = FakeParams("check_availability", {"check_in": "2026-11-02"}, [])
    b = FakeParams("check_availability", {"check_in": "2026-12-02"}, [])
    await asyncio.gather(router.handle(a), router.handle(b))  # type: ignore[arg-type]
    assert len(gateway.calls) == 2


async def test_gateway_call_error_fails_closed_and_settles_the_call() -> None:
    class BrokenCall(FakeGateway):
        async def call(self, name: str, arguments: dict[str, Any]) -> ToolResult:
            raise RuntimeError("ArmorIQ unreachable")

    output = RecordingOutput()
    router = make_router(BrokenCall("c1"), output)
    params = FakeParams("issue_refund", REFUND_250, output.log)
    await router.handle(params)  # type: ignore[arg-type]

    assert params.results and params.results[0][0].startswith("ERROR")
    assert router.pending_tools == []
    # The name is released, so a later call is not mistaken for a duplicate.
    again = FakeParams("issue_refund", REFUND_250, [])
    await router.handle(again)  # type: ignore[arg-type]
    assert again.results[0][0].startswith("ERROR")


async def test_hung_wait_is_a_refusal() -> None:
    class HungWait(FakeGateway):
        async def wait(self, held: ToolResult, timeout_s: float = 60.0) -> ToolResult:
            await asyncio.sleep(3600)
            raise AssertionError("unreachable")

    output = RecordingOutput()
    router = ToolRouter(
        HungWait("c1"), output, hold_timeout_s=0.05, filler_interval_s=1, wait_grace_s=0.05
    )
    await router.handle(FakeParams("issue_refund", REFUND_250, output.log))  # type: ignore[arg-type]
    await asyncio.wait_for(router.wait_for_holds(), timeout=2)

    assert output.outcomes[0].outcome is Outcome.NOT_RUN
    assert output.outcomes[0].reason == "hold_wait_overrun"


async def test_fake_verify_only_accepts_seed_identities() -> None:
    gateway = FakeGateway("c1")
    ok = await gateway.call("verify_guest", {"booking_ref": "lrk-1001 ", "last_name": "Okafor"})
    misheard = await gateway.call("verify_guest", {"booking_ref": "LRC-101", "last_name": "Okafor"})
    wrong_name = await gateway.call(
        "verify_guest", {"booking_ref": "LRK-1001", "last_name": "Brandt"}
    )
    assert '"verified": true' in ok.content and '"first_name": "Amara"' in ok.content
    assert misheard.content == '{"verified": false}'
    assert wrong_name.content == '{"verified": false}'


@pytest.mark.parametrize(
    ("reason", "phrase", "absent"),
    [
        ("rejected", "DECLINED by the manager", "in time"),
        ("timeout", "couldn't reach a manager in time", "DECLINED"),  # the bridge's reason
        ("approval_timeout", "couldn't reach a manager in time", "DECLINED"),
        ("hold_wait_error", "couldn't reach a manager in time", "DECLINED"),
    ],
)
def test_outcome_wording_separates_a_no_from_no_answer(
    reason: str, phrase: str, absent: str
) -> None:
    result = ToolResult(
        tool="issue_refund",
        decision=Decision.HOLD,
        outcome=Outcome.NOT_RUN,
        content="not done",
        reason=reason,
        armoriq_mode="live",
    )
    content = hold_outcome_message("issue_refund", result)["content"]
    assert phrase in content and absent not in content


class CommitThenSlow(FakeGateway):
    """The action commits at once (it is recorded in `calls`), then the reply is slow."""

    async def call(self, name: str, arguments: dict[str, Any]) -> ToolResult:
        result = await super().call(name, arguments)
        await asyncio.sleep(0.1)
        return result


REFUND_40 = {"booking_id": 1001, "amount": 40.0, "reason": "noise"}


async def start_then_interrupt(router: ToolRouter, params: FakeParams) -> None:
    """Pipecat cancels the handler task when the caller talks over the bot."""
    handler = asyncio.create_task(router.handle(params))  # type: ignore[arg-type]
    await asyncio.sleep(0.02)
    handler.cancel()
    await asyncio.gather(handler, return_exceptions=True)


async def test_barge_in_after_commit_keeps_the_outcome_and_never_runs_twice() -> None:
    gateway = CommitThenSlow("c1")
    output = RecordingOutput()
    router = make_router(gateway, output)
    first = FakeParams("issue_refund", REFUND_40, output.log)

    await start_then_interrupt(router, first)
    assert len(gateway.calls) == 1  # the refund committed before the interruption

    # The LLM, having seen the call cancelled, asks for the same refund again.
    again = FakeParams("issue_refund", REFUND_40, [])
    await router.handle(again)  # type: ignore[arg-type]
    assert "DUPLICATE" in again.results[0][0]

    await router.wait_for_holds()
    assert len(gateway.calls) == 1
    assert first.results == []  # the cancelled handler is not answered...
    assert output.log[-1] == "late:issue_refund:ran"  # ...the outcome reaches the context
    assert router.has_pending_holds() is False


async def test_barge_in_on_a_held_call_still_starts_the_hold() -> None:
    gateway = CommitThenSlow("c1", approval_delay_s=0.05)
    output = RecordingOutput()
    router = make_router(gateway, output)

    await start_then_interrupt(router, FakeParams("issue_refund", REFUND_250, output.log))
    await router.wait_for_holds()

    assert output.log[0] == f"say:{HOLD_ANNOUNCEMENT}"
    assert output.log[-1] == "outcome:issue_refund:ran"
    assert len(gateway.calls) == 1


async def test_hangup_cancels_an_acting_call_in_flight() -> None:
    gateway = CommitThenSlow("c1")
    output = RecordingOutput()
    router = make_router(gateway, output)

    await start_then_interrupt(router, FakeParams("issue_refund", REFUND_40, output.log))
    await router.close()
    await asyncio.sleep(0.15)

    assert output.outcomes == []  # nothing is delivered after hangup
    assert router.has_pending_holds() is False


async def test_handler_queued_during_hangup_never_reaches_gateway() -> None:
    gateway = CommitThenSlow("c1")
    router = make_router(gateway, RecordingOutput())
    in_flight = asyncio.create_task(router.handle(FakeParams("issue_refund", REFUND_40, [])))  # type: ignore[arg-type]
    await asyncio.sleep(0.02)

    closing = asyncio.create_task(router.close())
    await asyncio.sleep(0)  # close() is now awaiting the in-flight call's cancellation
    late = FakeParams("apply_comp_credit", {"booking_id": 1001, "amount": 20.0}, [])
    await router.handle(late)  # type: ignore[arg-type]
    await closing
    await asyncio.gather(in_flight, return_exceptions=True)

    assert [name for name, _ in gateway.calls] == ["issue_refund"]
    assert late.results[0][0].startswith("CALL_ENDED")


async def test_fake_wait_times_out_when_the_deadline_comes_before_approval() -> None:
    gateway = FakeGateway("c1", approval_delay_s=30)
    held = await gateway.call("issue_refund", REFUND_250)
    result = await gateway.wait(held, timeout_s=0.01)
    assert result.outcome is Outcome.NOT_RUN
    assert result.reason == "approval_timeout"


async def test_barge_in_cancels_a_read() -> None:
    gateway = CommitThenSlow("c1")
    output = RecordingOutput()
    router = make_router(gateway, output)

    await start_then_interrupt(router, FakeParams("check_availability", {"check_in": "x"}, []))
    await asyncio.sleep(0.15)

    assert output.log == []
    assert router.has_pending_holds() is False
