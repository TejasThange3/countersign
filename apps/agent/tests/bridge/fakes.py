"""Fakes for the bridge unit tests. Every ArmorIQ answer here is made up and named as a fake
(AGENTS.md rule 5); nothing in this file talks to ArmorIQ or hotel-mcp."""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from armoriq_sdk.session import EnforceResult, ReportOptions
from countersign_agent.bridge.enforcer import ArmorIQEnforcer
from countersign_agent.bridge.executor import ToolOutput
from countersign_agent.bridge.gateway import GovernedGateway
from countersign_agent.bridge.identity import CallIdentity
from countersign_agent.bridge.masking import Masker
from countersign_agent.bridge.tools import ToolInfo, convert_tools
from countersign_agent.contracts import GatewayEvent

UNVERIFIED = "real.person+unverified@example.org"
GUEST = "real.person+guest@example.org"
GUEST_ID = 7
OTHER_GUEST_ID = 9


def _schema(props: dict[str, str], required: list[str]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {k: {"type": v} for k, v in props.items()},
        "required": required,
    }


GUEST_ID_DESC = {"guest_id": "integer"}

FAKE_TOOL_INFOS = [
    ToolInfo(
        name="verify_guest",
        description="Verify a caller.",
        input_schema=_schema(
            {"booking_ref": "string", "last_name": "string"}, ["booking_ref", "last_name"]
        ),
        tags=["read"],
    ),
    ToolInfo(name="get_hotel_info", input_schema=_schema({}, []), tags=["read"]),
    ToolInfo(
        name="get_booking",
        input_schema=_schema(
            {"guest_id": "integer", "booking_id": "integer"}, ["guest_id", "booking_id"]
        ),
        tags=["read"],
    ),
    ToolInfo(
        name="issue_refund",
        input_schema=_schema(
            {
                "guest_id": "integer",
                "booking_id": "integer",
                "amount": "number",
                "reason": "string",
            },
            ["guest_id", "booking_id", "amount", "reason"],
        ),
        tags=["money"],
    ),
    ToolInfo(name="export_guest_list", input_schema=_schema({}, []), tags=["sensitive"]),
    ToolInfo(
        name="delete_guest_profile",
        input_schema=_schema({"target_guest_id": "integer"}, ["target_guest_id"]),
        tags=["sensitive"],
    ),
]

# Real hotel-mcp verify_guest result shapes (pinned by apps/mcp-server tests).
VERIFIED = {"verified": True, "guest_id": GUEST_ID, "first_name": "Ada", "bookings": []}
VERIFIED_OTHER = {"verified": True, "guest_id": OTHER_GUEST_ID, "first_name": "Bo", "bookings": []}
NOT_VERIFIED = {"verified": False, "guest_id": None, "first_name": None, "bookings": []}


class FakeIntentToken:
    def __init__(self, plan_id: str) -> None:
        self.plan_id = plan_id


class FakeArmorIQSession:
    """Stands in for armoriq_sdk ArmorIQSession. `decide` maps (tool, args) to a fake
    EnforceResult, or raises to simulate a broken SDK call."""

    def __init__(
        self,
        user_email: str,
        log: FakeArmorIQLog,
        decide: Callable[[str, dict[str, Any]], EnforceResult],
    ) -> None:
        self.user_email = user_email
        self.log = log
        self.decide = decide
        self.closed = False

    def start_plan(self, tool_calls: list[dict[str, Any]], goal: str | None = None) -> Any:
        if self.log.fail_plan:
            raise RuntimeError("fake: plan capture failed")
        self.log.plans.append((self.user_email, [c["name"] for c in tool_calls], goal))
        return FakeIntentToken(f"plan-{len(self.log.plans)}")

    def check(
        self, tool_name: str, tool_args: dict[str, Any], user_email: str | None = None
    ) -> EnforceResult:
        time.sleep(self.log.check_seconds)
        self.log.checks.append((user_email or "", tool_name, dict(tool_args)))
        return self.decide(tool_name, tool_args)

    def report(
        self,
        tool_name: str,
        tool_args: dict[str, Any],
        result: Any,
        opts: ReportOptions | None = None,
    ) -> None:
        self.log.reports.append((tool_name, opts.status if opts else None))
        self.log.reported_by.append((tool_name, self.user_email))

    def close(self) -> None:
        if self.log.fail_close:
            raise RuntimeError("fake: session close failed")
        self.closed = True


class FakeArmorIQLog:
    def __init__(self) -> None:
        self.plans: list[tuple[str, list[str], str | None]] = []
        self.checks: list[tuple[str, str, dict[str, Any]]] = []
        self.reports: list[tuple[str, str | None]] = []
        self.reported_by: list[tuple[str, str]] = []
        self.fail_plan = False
        self.fail_close = False
        self.check_seconds = 0.0


def fake_allow(tool: str, args: dict[str, Any]) -> EnforceResult:
    return EnforceResult(allowed=True, action="allow", reason="enforcement_passed")


def fake_policy(tool: str, args: dict[str, Any]) -> EnforceResult:
    """A fake of the console policy: refunds hold above 100, sensitive tools are blocked."""
    if tool in {"export_guest_list", "delete_guest_profile"}:
        return EnforceResult(
            allowed=False, action="block", reason="tool_denied", matched_policy="fake-policy"
        )
    if tool == "issue_refund" and float(args.get("amount", 0)) > 100:
        return EnforceResult(
            allowed=False,
            action="hold",
            reason="rule_action_hold",
            matched_policy="fake-policy",
            delegation_id="d-1",
        )
    return EnforceResult(allowed=True, action="allow", reason="enforcement_passed")


class FakeApprovals:
    """Stands in for CheckedApprovals: scripted delegation statuses, no HTTP."""

    def __init__(self, statuses: list[str | Exception] | None = None) -> None:
        self.statuses = statuses or ["pending"]
        self.polls = 0
        self.marked: list[tuple[str, str, str | None]] = []

    def get_delegation_status(self, delegation_id: str) -> str:
        item = self.statuses[min(self.polls, len(self.statuses) - 1)]
        self.polls += 1
        if isinstance(item, Exception):
            raise item
        return item

    def mark_delegation_executed(
        self, user_email: str, delegation_id: str, plan_id: str | None = None
    ) -> None:
        self.marked.append((user_email, delegation_id, plan_id))


class FakeMCP:
    """Stands in for hotel-mcp: records calls, answers from a table."""

    def __init__(self, answers: dict[str, Any] | None = None) -> None:
        self.answers: dict[str, Any] = {
            "verify_guest": VERIFIED,
            "get_hotel_info": {"name": "The Larkspur"},
            "get_booking": {"booking_id": 1},
            "issue_refund": {"payment_id": 1, "amount": 40},
            "export_guest_list": [{"email": "someone@example.net"}],
            "delete_guest_profile": {"deleted": True},
            **(answers or {}),
        }
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.closed = False

    async def list_tools(self) -> list[ToolInfo]:
        return FAKE_TOOL_INFOS

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> ToolOutput:
        self.calls.append((name, dict(arguments)))
        answer = self.answers[name]
        if isinstance(answer, Exception):
            raise answer
        if isinstance(answer, ToolOutput):
            return answer
        return ToolOutput(data=answer)

    async def close(self) -> None:
        self.closed = True


class Harness:
    """A GovernedGateway wired to fakes, plus everything a test wants to inspect."""

    def __init__(
        self,
        decide: Callable[[str, dict[str, Any]], EnforceResult] = fake_policy,
        approvals: FakeApprovals | None = None,
        mcp: FakeMCP | None = None,
        max_failed_verifies: int = 3,
    ) -> None:
        self.log = FakeArmorIQLog()
        self.approvals = approvals or FakeApprovals()
        self.mcp = mcp or FakeMCP()
        self.events: list[GatewayEvent] = []
        self.sessions: list[FakeArmorIQSession] = []
        self.decide = decide
        self.max_failed_verifies = max_failed_verifies

    def _session(self, email: str) -> FakeArmorIQSession:
        session = FakeArmorIQSession(email, self.log, lambda t, a: self.decide(t, a))
        self.sessions.append(session)
        return session

    async def _sink(self, event: GatewayEvent) -> None:
        self.events.append(event)

    def kinds(self) -> list[str]:
        return [e.kind for e in self.events]

    async def open(self, enforcer: Any = None) -> GovernedGateway:
        tools = convert_tools(FAKE_TOOL_INFOS)
        gateway = GovernedGateway(
            "call-1",
            tools=tools,
            enforcer=enforcer
            or ArmorIQEnforcer(
                session_factory=self._session,
                approvals=self.approvals,
                tool_names=list(tools),
                poll_seconds=0.01,
            ),
            executor=self.mcp,
            identity=CallIdentity(self.max_failed_verifies),
            identities={"unverified": UNVERIFIED, "guest": GUEST},
            masker=Masker({UNVERIFIED: "<unverified>", GUEST: "<guest>"}),
            events=self._sink,
        )
        await gateway.start()
        return gateway
