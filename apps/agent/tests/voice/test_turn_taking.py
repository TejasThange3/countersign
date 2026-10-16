"""A hold decided while the caller is talking must not make the bot talk over them."""

from __future__ import annotations

import asyncio
from typing import Any

from countersign_agent.contracts import Decision, Outcome, ToolResult
from countersign_agent.voice.fake_gateway import FakeGatewayFactory
from countersign_agent.voice.session import PipelineCallOutput
from countersign_agent.voice.text_mode import TextSession
from fakes import FakeScriptedLLM, hotel_script, make_settings
from pipecat.frames.frames import (
    InterimTranscriptionFrame,
    LLMMessagesAppendFrame,
    LLMRunFrame,
    TranscriptionFrame,
    TTSSpeakFrame,
)
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import LLMContextAggregatorPair

APPROVED = ToolResult(
    tool="issue_refund",
    decision=Decision.HOLD,
    outcome=Outcome.RAN,
    content="{}",
    armoriq_mode="disabled",
)


def outcome_seen(messages: list[dict[str, Any]]) -> bool:
    return any("earlier issue_refund request" in str(m.get("content")) for m in messages)


async def test_approval_during_caller_speech_waits_for_the_turn_to_end() -> None:
    """Frame level: a real pipeline, the approval released mid-turn."""
    factory = FakeGatewayFactory(approval_delay_s=30)
    llm = FakeScriptedLLM(hotel_script)
    session = await TextSession.open("turns", factory, make_settings(), llm_factory=lambda _s: llm)
    try:
        await session.send("Please refund 250 dollars", wait_for_holds=False)
        assert llm.inferences == 1

        # The caller starts talking; the manager approves while they are mid-sentence.
        await session._worker.queue_frame(
            InterimTranscriptionFrame(text="I also want", user_id="caller", timestamp="t")
        )
        await asyncio.sleep(0.3)
        assert session.core.output.caller_speaking
        factory.opened[0].release()
        await asyncio.sleep(0.5)
        assert llm.inferences == 1  # nothing spoken over the caller

        # The caller finishes: one inference answers their words and the outcome together.
        await session._worker.queue_frame(
            TranscriptionFrame(text="I also want a late checkout", user_id="caller", timestamp="t")
        )
        await asyncio.sleep(1.5)
        assert llm.inferences == 2
        assert outcome_seen(llm.seen_messages[-1])
    finally:
        await session.close()


class RecordingWorker:
    def __init__(self) -> None:
        self.frames: list[object] = []

    async def queue_frame(self, frame: object) -> None:
        self.frames.append(frame)


async def fire(aggregator: Any, event: str, *args: Any) -> None:
    await aggregator._call_event_handler(event, *args)
    await asyncio.sleep(0)  # handlers run as tasks


async def wired() -> tuple[PipelineCallOutput, Any, RecordingWorker]:
    output = PipelineCallOutput()
    worker = RecordingWorker()
    output.worker = worker  # type: ignore[assignment]  # only queue_frame is used
    aggregator = LLMContextAggregatorPair(LLMContext()).user()
    output.watch_caller_turns(aggregator)
    return output, aggregator, worker


async def test_outcome_with_no_caller_speech_is_spoken_verbatim_at_once() -> None:
    # The decision is not worded by the LLM (it once said "pending" after an approval):
    # the fixed sentence is recorded in the context as said, then spoken.
    output, _aggregator, worker = await wired()
    await output.deliver_hold_outcome("issue_refund", APPROVED)
    append, speak = worker.frames
    assert isinstance(append, LLMMessagesAppendFrame) and append.run_llm is False
    assert isinstance(speak, TTSSpeakFrame)
    assert speak.text.startswith("Good news: the manager approved it")
    assert append.messages[-1] == {"role": "assistant", "content": speak.text}


async def test_outcome_during_a_wordless_turn_runs_once_when_it_ends() -> None:
    output, aggregator, worker = await wired()
    await fire(aggregator, "on_user_turn_started", None)
    await output.deliver_hold_outcome("issue_refund", APPROVED)
    await output.deliver_hold_outcome("apply_comp_credit", APPROVED)  # two coalesce into one
    assert [f.run_llm for f in worker.frames] == [False, False]  # type: ignore[attr-defined]

    await fire(aggregator, "on_user_turn_stopped", None, None)
    assert sum(isinstance(f, LLMRunFrame) for f in worker.frames) == 1


async def caller_words_written(
    aggregator: Any, worker: RecordingWorker, *, outcome_first: bool
) -> None:
    """What the aggregator does: queued appends land in the context, then the words."""
    appended = [
        m for f in worker.frames if isinstance(f, LLMMessagesAppendFrame) for m in f.messages
    ]
    if outcome_first:
        aggregator.context.add_messages(appended)
    aggregator.context.add_message({"role": "user", "content": "and a late checkout"})
    await fire(aggregator, "on_user_turn_message_added", None)


async def test_caller_words_carry_the_outcome_without_a_second_inference() -> None:
    output, aggregator, worker = await wired()
    await fire(aggregator, "on_user_turn_started", None)
    await output.deliver_hold_outcome("issue_refund", APPROVED)
    await caller_words_written(aggregator, worker, outcome_first=True)
    await fire(aggregator, "on_user_turn_stopped", None, None)
    assert not any(isinstance(f, LLMRunFrame) for f in worker.frames)


async def test_outcome_that_lands_after_the_words_is_still_spoken() -> None:
    # Race: the caller's words reach the context before the queued outcome does, so the
    # inference for the words never saw it. The end of the turn must speak it.
    output, aggregator, worker = await wired()
    await fire(aggregator, "on_user_turn_started", None)
    await output.deliver_hold_outcome("issue_refund", APPROVED)
    await caller_words_written(aggregator, worker, outcome_first=False)
    await fire(aggregator, "on_user_turn_stopped", None, None)
    assert sum(isinstance(f, LLMRunFrame) for f in worker.frames) == 1
