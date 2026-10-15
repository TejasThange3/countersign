"""The contract between the voice pipeline and the governed tool gateway.

Owned by the main session. The `voice` lane calls a `ToolGateway`; the `bridge` lane implements
it. Neither lane edits this file: request changes under "Needs from main". Keeping the seam this
small is what lets both lanes build in parallel without touching each other's files.

Flow for one phone call:
    gateway = await factory.open_call(call_id)
    tools = gateway.tool_specs()            # what the LLM may call (identity args removed)
    result = await gateway.call(name, args)  # governed by ArmorIQ unless DISABLE_ARMORIQ=1
    ... (holds: result.decision == HOLD; await gateway.wait(result) without blocking audio)
    await gateway.close()
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal, Protocol

from pydantic import BaseModel, Field


class Decision(StrEnum):
    ALLOW = "allow"
    HOLD = "hold"
    BLOCK = "block"
    # ArmorIQ unreachable or errored: treated as a block (fail closed), shown differently.
    UNAVAILABLE = "unavailable"


class Outcome(StrEnum):
    RAN = "ran"  # the tool executed (allowed, or held then approved)
    PENDING = "pending"  # held; waiting for an approver
    NOT_RUN = "not_run"  # blocked, rejected, timed out, or unavailable
    ERROR = "error"  # the tool itself failed after being allowed


class ToolSpec(BaseModel):
    """One tool as the LLM sees it. Identity arguments (guest_id) are already stripped."""

    name: str
    description: str
    parameters: dict[str, Any]  # JSON Schema object
    tier: Literal["read", "write", "money", "sensitive"]


class ToolResult(BaseModel):
    tool: str
    decision: Decision
    outcome: Outcome
    # Text the LLM receives as the function result. Never contains raw policy internals the
    # caller could use to probe the rules; the full detail is in `reason`/events.
    content: str
    reason: str | None = None  # ArmorIQ reason code, e.g. tool_denied, rule_action_hold
    policy: str | None = None
    plan_id: str | None = None
    delegation_id: str | None = None
    armoriq_mode: Literal["live", "disabled"]
    latency_ms: float = 0.0  # ArmorIQ overhead only (plan + check), not approval wait time


class GatewayEvent(BaseModel):
    """Published for the dashboard and the eval recorder (Redis pub/sub later)."""

    call_id: str
    kind: Literal[
        "identity_changed",  # unverified -> verified guest
        "tool_requested",
        "tool_decided",
        "hold_resolved",  # approved / rejected / timeout
        "tool_finished",
    ]
    at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    data: dict[str, Any] = Field(default_factory=dict)  # never contains emails or secrets


EventSink = Callable[[GatewayEvent], Awaitable[None]]


class ToolGateway(Protocol):
    """One instance per phone call."""

    call_id: str

    def tool_specs(self) -> list[ToolSpec]:
        """Tools the LLM may call now. Stable for the whole call (the plan is declared once)."""
        ...

    async def call(self, name: str, arguments: dict[str, Any]) -> ToolResult:
        """Run one tool through ArmorIQ. Returns quickly on HOLD (outcome PENDING); it never
        waits for a human here, so the voice pipeline can keep talking."""
        ...

    async def wait(self, held: ToolResult, timeout_s: float = 60.0) -> ToolResult:
        """Wait for an approver on a HOLD, without blocking the event loop. Cancel-safe: if the
        caller hangs up, cancelling this stops polling and the tool never runs. Timeout is a
        refusal."""
        ...

    async def close(self) -> None: ...


class GatewayFactory(Protocol):
    async def open_call(self, call_id: str, events: EventSink | None = None) -> ToolGateway: ...
