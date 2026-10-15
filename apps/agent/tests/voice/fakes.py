"""Test-only fakes: a scripted LLM that stands in for Gemini, and helpers to build sessions."""

from __future__ import annotations

import json
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from countersign_agent.voice.config import AgentSettings
from pipecat.frames.frames import (
    Frame,
    FunctionCallFromLLM,
    LLMContextFrame,
    LLMFullResponseEndFrame,
    LLMFullResponseStartFrame,
)
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.frame_processor import FrameDirection
from pipecat.services.llm_service import LLMService


@dataclass
class Step:
    """What the fake LLM does for one inference: say text, call tools, or both."""

    text: str = ""
    calls: list[tuple[str, dict[str, Any]]] = field(default_factory=list)


Script = Callable[[list[dict[str, Any]]], Step]


class FakeScriptedLLM(LLMService):
    """Answers each inference by calling `script(messages)`. Records what it was shown."""

    def __init__(self, script: Script) -> None:
        super().__init__()
        self._script = script
        self.seen_tool_names: list[list[str]] = []
        self.inferences = 0
        self.seen_messages: list[list[dict[str, Any]]] = []

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)
        if isinstance(frame, LLMContextFrame):
            await self._respond(frame.context)
        else:
            await self.push_frame(frame, direction)

    async def _respond(self, context: LLMContext) -> None:
        self.inferences += 1
        tools = context.tools
        names = [t.name for t in tools.standard_tools] if hasattr(tools, "standard_tools") else []
        self.seen_tool_names.append(names)
        messages = [dict(m) for m in context.get_messages()]
        self.seen_messages.append(messages)
        step = self._script(messages)
        await self.push_frame(LLMFullResponseStartFrame())
        await self.start_ttfb_metrics()
        if step.text:
            await self.stop_ttfb_metrics()
            await self._push_llm_text(step.text)
        await self.run_function_calls(
            [
                FunctionCallFromLLM(
                    function_name=name,
                    tool_call_id=f"call-{uuid.uuid4().hex[:8]}",
                    arguments=args,
                    context=context,
                )
                for name, args in step.calls
            ]
        )
        await self.push_frame(LLMFullResponseEndFrame())


def last(messages: list[dict[str, Any]]) -> dict[str, Any]:
    return messages[-1] if messages else {}


def text_of(message: dict[str, Any]) -> str:
    content = message.get("content", "")
    return content if isinstance(content, str) else json.dumps(content)


def hotel_script(messages: list[dict[str, Any]]) -> Step:
    """A tiny front-desk brain: enough to drive allow / hold / block paths deterministically."""
    msg = last(messages)
    role = msg.get("role")
    text = text_of(msg).lower()
    if role == "tool":
        if "still_waiting" in text:
            return Step(text="I'm still waiting on the manager, thanks for your patience.")
        if "not permitted" in text:
            return Step(text="I'm sorry, I can't do that.")
        return Step(text="Done. " + text_of(msg)[:60])
    if role == "developer" and "approved and completed" in text:
        return Step(text="Good news, the manager approved it and it's done.")
    if role == "developer":
        return Step(text="I'm sorry, the manager did not approve that.")
    if "availab" in text:
        return Step(
            calls=[("check_availability", {"check_in": "2026-11-02", "check_out": "2026-11-04"})]
        )
    if "refund" in text:
        amount = 250.0 if "250" in text else 40.0
        return Step(
            calls=[("issue_refund", {"booking_id": 1001, "amount": amount, "reason": "test"})]
        )
    if "export" in text:
        return Step(calls=[("export_guest_list", {})])
    return Step(text="How can I help?")


def make_settings(**overrides: Any) -> AgentSettings:
    base: dict[str, Any] = {
        "gemini_api_key": "",
        "groq_api_key": "",
        "elevenlabs_api_key": "",
        "hold_timeout_s": 5.0,
        "hold_filler_interval_s": 0.05,
    }
    base.update(overrides)
    return AgentSettings(_env_file=None, **base)  # type: ignore[call-arg]  # pydantic-settings init kwarg
