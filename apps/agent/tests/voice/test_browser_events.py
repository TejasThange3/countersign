"""The website's live events: transcript lines, decisions, holds and interruptions."""

from __future__ import annotations

from typing import Any

from countersign_agent.contracts import Decision, Outcome, ToolResult
from countersign_agent.voice.browser_events import BrowserEventRelay
from pipecat.frames.frames import (
    InterruptionFrame,
    LLMFullResponseEndFrame,
    LLMFullResponseStartFrame,
    LLMTextFrame,
    TranscriptionFrame,
    TTSSpeakFrame,
)
from pipecat.observers.base_observer import FramePushed
from pipecat.processors.frame_processor import FrameDirection


class Worker:
    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    async def queue_frame(self, frame: Any) -> None:
        self.events.append(frame.message)


def pushed(frame: Any, *, first: bool = True) -> FramePushed:
    return FramePushed(
        source=None,  # type: ignore[arg-type]
        destination=None,  # type: ignore[arg-type]
        frame=frame,
        direction=FrameDirection.DOWNSTREAM,
        timestamp=0,
        first_push=first,
    )


def result(outcome: Outcome, decision: Decision = Decision.HOLD) -> ToolResult:
    return ToolResult(
        tool="issue_refund",
        decision=decision,
        outcome=outcome,
        content="secret tool output",
        reason="rule_action_hold",
        armoriq_mode="live",
    )


async def test_transcript_and_reply_lines() -> None:
    worker = Worker()
    relay = BrowserEventRelay(worker)
    for frame in [
        TranscriptionFrame("refund forty dollars", "u", "t"),
        LLMFullResponseStartFrame(),
        LLMTextFrame("That needs "),
        LLMTextFrame("approval."),
        LLMFullResponseEndFrame(),
        TTSSpeakFrame("One moment."),
    ]:
        await relay.on_push_frame(pushed(frame))
    await relay.on_push_frame(pushed(TTSSpeakFrame("again"), first=False))  # seen once only

    assert worker.events == [
        {"type": "caller", "text": "refund forty dollars"},
        {"type": "agent", "text": "That needs approval."},
        {"type": "agent", "text": "One moment."},
    ]


async def test_interruption_drops_the_half_reply() -> None:
    worker = Worker()
    relay = BrowserEventRelay(worker)
    await relay.on_push_frame(pushed(LLMFullResponseStartFrame()))
    await relay.on_push_frame(pushed(LLMTextFrame("half a sent")))
    await relay.on_push_frame(pushed(InterruptionFrame()))
    await relay.on_push_frame(pushed(LLMFullResponseEndFrame()))
    assert worker.events == [{"type": "interrupt"}]


async def test_hold_then_settled_and_no_tool_output_leaks() -> None:
    worker = Worker()
    relay = BrowserEventRelay(worker)
    await relay.on_result(result(Outcome.PENDING))
    await relay.on_result(result(Outcome.RAN))

    kinds = [e["type"] for e in worker.events]
    assert kinds == ["decision", "held", "decision", "settled"]
    assert all("content" not in e for e in worker.events)


async def test_allowed_call_is_just_a_decision() -> None:
    worker = Worker()
    await BrowserEventRelay(worker).on_result(result(Outcome.RAN, Decision.ALLOW))
    assert [e["type"] for e in worker.events] == ["decision"]


async def test_ready_once_caller_audio_flows() -> None:
    from pipecat.frames.frames import InputAudioRawFrame

    worker = Worker()
    relay = BrowserEventRelay(worker)
    for _ in range(3):
        await relay.on_push_frame(
            pushed(InputAudioRawFrame(audio=b"\x00\x00", sample_rate=16_000, num_channels=1))
        )
    assert worker.events == [{"type": "ready"}]
