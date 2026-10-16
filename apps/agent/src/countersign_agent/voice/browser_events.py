"""Live events for the website's voice call, sent as JSON text on the call's WebSocket.

    {"type": "ready"}                  the call is listening (the ArmorIQ session is open)
    {"type": "caller", "text": ...}    what the caller said (final transcript)
    {"type": "agent", "text": ...}     what the agent said (one LLM reply, or a fixed line)
    {"type": "interrupt"}              the caller talked over the agent: drop queued audio
    {"type": "decision", ...}          one ArmorIQ result (tool, decision, outcome, reason, plan)
    {"type": "held", "tool": ...}      a request is waiting for a manager
    {"type": "settled", "tool": ...}   that request has been decided (or timed out)

The relay only reads frames and queues small message frames; it never changes the call.
"""

from __future__ import annotations

import logging
from typing import Any

from pipecat.frames.frames import (
    InputAudioRawFrame,
    InterruptionFrame,
    LLMFullResponseEndFrame,
    LLMFullResponseStartFrame,
    LLMTextFrame,
    OutputTransportMessageUrgentFrame,
    TranscriptionFrame,
    TTSSpeakFrame,
)
from pipecat.observers.base_observer import BaseObserver, FramePushed
from pipecat.processors.frame_processor import FrameDirection

from countersign_agent.contracts import Outcome, ToolResult

logger = logging.getLogger(__name__)


def decision_event(result: ToolResult) -> dict[str, Any]:
    """A result for display: no tool output (`content`), only what ArmorIQ decided."""
    return {
        "type": "decision",
        "tool": result.tool,
        "decision": result.decision.value,
        "outcome": result.outcome.value,
        "reason": result.reason,
        "plan_id": result.plan_id,
        "armoriq_mode": result.armoriq_mode,
    }


class BrowserEventRelay(BaseObserver):
    def __init__(self, worker: Any = None) -> None:
        super().__init__()
        # The pipeline worker takes its observers when it is built, so it is attached after.
        self.worker = worker
        self._reply: list[str] | None = None
        self._ready = False

    async def send(self, event: dict[str, Any]) -> None:
        if self.worker is not None:
            await self.worker.queue_frame(OutputTransportMessageUrgentFrame(message=event))

    async def on_result(self, result: ToolResult) -> None:
        await self.send(decision_event(result))
        kind = "held" if result.outcome is Outcome.PENDING else None
        if result.decision.value == "hold" and result.outcome is not Outcome.PENDING:
            kind = "settled"
        if kind:
            await self.send({"type": kind, "tool": result.tool})

    async def on_push_frame(self, data: FramePushed) -> None:
        if not data.first_push or data.direction is not FrameDirection.DOWNSTREAM:
            return
        frame = data.frame
        if isinstance(frame, InputAudioRawFrame):
            # The first caller audio through the pipeline proves the line is live. (A message
            # queued as the pipeline starts is lost: the socket output isn't writing yet.)
            if not self._ready:
                self._ready = True
                await self.send({"type": "ready"})
        elif isinstance(frame, TranscriptionFrame) and frame.text.strip():
            await self.send({"type": "caller", "text": frame.text.strip()})
        elif isinstance(frame, LLMFullResponseStartFrame):
            self._reply = []
        elif isinstance(frame, LLMTextFrame) and self._reply is not None:
            self._reply.append(frame.text)
        elif isinstance(frame, LLMFullResponseEndFrame) and self._reply is not None:
            text = "".join(self._reply).strip()
            self._reply = None
            if text:
                await self.send({"type": "agent", "text": text})
        elif isinstance(frame, TTSSpeakFrame) and frame.text.strip():
            await self.send({"type": "agent", "text": frame.text.strip()})
        elif isinstance(frame, InterruptionFrame):
            self._reply = None
            await self.send({"type": "interrupt"})
