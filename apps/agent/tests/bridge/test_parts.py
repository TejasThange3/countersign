"""The bridge's smaller parts: schema conversion, identity, verdict mapping, masking, factory."""

from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from typing import ClassVar

import pytest
from armoriq_sdk.session import EnforceResult
from countersign_agent.bridge.enforcer import (
    ArmorIQEnforcer,
    DisabledEnforcer,
    UnavailableEnforcer,
    to_verdict,
)
from countersign_agent.bridge.gateway_factory import GovernedGatewayFactory
from countersign_agent.bridge.identity import CallIdentity, Verify
from countersign_agent.bridge.masking import Masker, install_masked_logging
from countersign_agent.bridge.redact import REDACTED
from countersign_agent.bridge.settings import BridgeSettings
from countersign_agent.bridge.tools import ToolInfo, convert_tools, strip_identity, tier_of
from countersign_agent.contracts import Decision, Outcome

from .fakes import FAKE_TOOL_INFOS, GUEST, UNVERIFIED, FakeApprovals, FakeMCP

# --- schema conversion ---


def test_strip_identity_removes_guest_id_and_leaves_input_alone() -> None:
    schema = {
        "type": "object",
        "properties": {"guest_id": {"type": "integer"}, "amount": {"type": "number"}},
        "required": ["guest_id", "amount"],
    }
    stripped = strip_identity(schema)
    assert stripped == {
        "type": "object",
        "properties": {"amount": {"type": "number"}},
        "required": ["amount"],
    }
    assert "guest_id" in schema["properties"]  # a copy, not a mutation


def test_strip_identity_handles_schemas_without_properties() -> None:
    assert strip_identity({"type": "object"}) == {"type": "object"}


@pytest.mark.parametrize(
    ("tags", "tier"),
    [
        (["money"], "money"),
        (["read"], "read"),
        ([], None),
        (["read", "write"], None),
        (["x"], None),
    ],
)
def test_tier_needs_exactly_one_known_tag(tags: list[str], tier: str | None) -> None:
    assert tier_of(tags) == tier


def test_convert_tools_drops_untiered_tools_and_flags_guest_scoped_ones() -> None:
    infos = [*FAKE_TOOL_INFOS, ToolInfo(name="mystery", input_schema={}, tags=[])]
    tools = convert_tools(infos)
    assert "mystery" not in tools
    assert tools["issue_refund"].needs_guest_id
    assert not tools["delete_guest_profile"].needs_guest_id  # target_guest_id is not identity
    assert not tools["verify_guest"].needs_guest_id


# --- identity ---


def test_identity_state_machine() -> None:
    ident = CallIdentity(max_failed_verifies=2)
    assert not ident.verified
    assert ident.record_verify(False, None) is Verify.FAILED
    assert ident.record_verify(True, 7) is Verify.SWITCHED
    assert ident.guest_id == 7
    assert ident.record_verify(True, 7) is Verify.SAME_GUEST
    assert ident.record_verify(True, 8) is Verify.OTHER_GUEST
    assert ident.guest_id == 7
    assert not ident.locked_out
    ident.record_verify(False, None)
    assert ident.locked_out


def test_verified_true_without_guest_id_is_a_failure() -> None:
    ident = CallIdentity(max_failed_verifies=3)
    assert ident.record_verify(True, None) is Verify.FAILED
    assert not ident.verified


# --- verdict mapping ---


@pytest.mark.parametrize(
    ("result", "decision"),
    [
        (EnforceResult(allowed=True, action="allow"), Decision.ALLOW),
        (EnforceResult(allowed=False, action="block", reason="tool_denied"), Decision.BLOCK),
        (EnforceResult(allowed=False, action="hold", delegation_id="d"), Decision.HOLD),
        (EnforceResult(allowed=True, action="allow", delegation_id="d"), Decision.UNAVAILABLE),
        (EnforceResult(allowed=False, action="hold"), Decision.UNAVAILABLE),
        (
            EnforceResult(allowed=False, action="block", reason="enforce-unavailable: x"),
            Decision.UNAVAILABLE,
        ),
        (
            EnforceResult(allowed=False, action="block", reason="tool-not-in-plan: x"),
            Decision.BLOCK,
        ),
    ],
)
def test_to_verdict(result: EnforceResult, decision: Decision) -> None:
    assert to_verdict(result, 1.0).decision is decision


class FakeSharedClientSession:
    """Mimics the SDK: for_user().start_session() writes the email onto the SHARED client,
    and start_plan() mints the token from whatever is there at that moment."""

    shared: ClassVar[dict[str, str]] = {}

    def __init__(self, email: str, minted: list[tuple[str, str]]) -> None:
        FakeSharedClientSession.shared["override"] = email
        self.email = email
        self.minted = minted

    def start_plan(self, tool_calls: list[dict[str, object]], goal: str | None = None) -> None:
        time.sleep(0.05)  # another call's start_session lands here without the lock
        self.minted.append((self.email, FakeSharedClientSession.shared["override"]))

    def close(self) -> None:
        pass


async def test_concurrent_calls_never_mint_a_plan_for_another_identity() -> None:
    minted: list[tuple[str, str]] = []
    plan_thread = ThreadPoolExecutor(max_workers=1)  # one shared plan thread, as in production

    def enforcer() -> ArmorIQEnforcer:
        return ArmorIQEnforcer(
            session_factory=lambda email: FakeSharedClientSession(email, minted),  # type: ignore[arg-type,return-value]
            approvals=FakeApprovals(),
            tool_names=["get_hotel_info"],
            poll_seconds=0.01,
            plan_executor=plan_thread,
        )

    await asyncio.gather(enforcer().start(UNVERIFIED, "a"), enforcer().start(GUEST, "b"))
    assert sorted(minted) == sorted([(UNVERIFIED, UNVERIFIED), (GUEST, GUEST)])


# --- masking ---


def test_masker_masks_identities_secrets_personal_keys_and_stray_emails() -> None:
    masker = Masker({GUEST: "<guest>", "ak_live_fakefake": "<api-key>", "": "<jwt>"})
    cleaned = masker.clean(
        {
            "user": GUEST,
            "msg": "401 with ak_live_fakefake for a.b@c.io",
            "apiKey": "x",
            "last_name": "Okafor",
            "rows": [{"email": "z@y.co", "tier": "gold"}],
        }
    )
    assert cleaned == {
        "user": "<guest>",
        "msg": "401 with <api-key> for <email>",
        "apiKey": "<redacted>",
        "last_name": "<masked>",
        "rows": [{"email": "<masked>", "tier": "gold"}],
    }
    assert masker.clean("plain text") == "plain text"  # empty secrets never match


def test_masker_masks_personal_keys_inside_json_string_content() -> None:
    # Tool results reach events as a JSON string (ToolResult.content), not a dict.
    content = json.dumps({"guest_name": "Amara Okafor", "phone": "555", "room_number": "103"})
    cleaned = Masker({}).clean({"content": content, "note": "{not json"})
    assert json.loads(cleaned["content"]) == {
        "guest_name": "<masked>",
        "phone": "<masked>",
        "room_number": "103",
    }
    assert cleaned["note"] == "{not json"


def test_masker_redacts_credentials_inside_json_string_content() -> None:
    fake = "fake-not-a-secret"
    inner = json.dumps({"authorization": fake, "ok": 1})
    content = json.dumps({"rows": [{"password": fake, "api_token": fake, "detail": inner}]})
    cleaned = json.loads(Masker({}).clean({"content": content})["content"])
    row = cleaned["rows"][0]
    assert row["password"] == REDACTED
    assert row["api_token"] == REDACTED
    assert json.loads(row["detail"]) == {"authorization": REDACTED, "ok": 1}
    assert fake not in json.dumps(cleaned)


def test_masker_handles_padded_and_pathologically_nested_json_text() -> None:
    fake = "fake-not-a-secret"
    padded = Masker({}).clean({"c": ' \n{"password": "%s"}' % fake})  # noqa: UP031  # literal braces
    assert fake not in padded["c"]
    deep = Masker({}).clean({"c": "[" * 5000 + "]" * 5000})  # guest-written text can look like this
    assert deep["c"] == "<masked>"


@pytest.fixture
def restore_root_logging() -> Iterator[None]:
    root = logging.getLogger()
    handlers, level = root.handlers[:], root.level
    yield
    root.handlers[:] = handlers
    root.setLevel(level)


@pytest.mark.usefixtures("restore_root_logging")
def test_logged_exceptions_are_masked(capsys: pytest.CaptureFixture[str]) -> None:
    install_masked_logging(Masker({UNVERIFIED: "<unverified>", "ak_live_fake": "<api-key>"}))
    try:
        raise RuntimeError(f"401 for {UNVERIFIED} with ak_live_fake")
    except RuntimeError:
        logging.getLogger("countersign_agent.test").exception("boom")
    err = capsys.readouterr().err
    assert "Traceback" in err
    assert "<unverified>" in err and "<api-key>" in err
    assert "real.person" not in err and "ak_live_fake" not in err


# --- factory ---


def settings(**overrides: object) -> BridgeSettings:
    base: dict[str, object] = {
        "armoriq_user_unverified": UNVERIFIED,
        "armoriq_user_guest": GUEST,
        "disable_armoriq": False,
    }
    # _env_file=None: unit tests never read the real .env.
    return BridgeSettings(_env_file=None, **(base | overrides))  # type: ignore[arg-type,call-arg]


async def test_factory_disabled_mode_builds_a_baseline_gateway() -> None:
    mcp = FakeMCP()

    async def connect() -> FakeMCP:
        return mcp

    factory = GovernedGatewayFactory(settings(disable_armoriq=True), executor_factory=connect)
    gw = await factory.open_call("call-9")
    assert isinstance(gw._enforcer, DisabledEnforcer)
    assert {s.name for s in gw.tool_specs()} == {t.name for t in FAKE_TOOL_INFOS}
    result = await gw.call("export_guest_list", {})
    assert result.outcome is Outcome.RAN and result.armoriq_mode == "disabled"
    await gw.close()
    assert mcp.closed


async def test_factory_without_armoriq_key_fails_closed_not_crashes() -> None:
    async def connect() -> FakeMCP:
        return FakeMCP()

    # No API key: building the client raises, the call still opens and every tool is refused.
    factory = GovernedGatewayFactory(settings(armoriq_api_key=""), executor_factory=connect)
    gw = await factory.open_call("call-10")
    assert isinstance(gw._enforcer, UnavailableEnforcer)
    result = await gw.call("get_hotel_info", {})
    assert result.decision is Decision.UNAVAILABLE
    assert json.loads(json.dumps(result.model_dump(mode="json")))["armoriq_mode"] == "live"


async def test_factory_closes_mcp_if_discovery_fails() -> None:
    mcp = FakeMCP()

    async def broken_list() -> list[ToolInfo]:
        raise ConnectionError("fake: tools/list failed")

    mcp.list_tools = broken_list  # type: ignore[method-assign]  # fake failure

    async def connect() -> FakeMCP:
        return mcp

    factory = GovernedGatewayFactory(settings(disable_armoriq=True), executor_factory=connect)
    with pytest.raises(ConnectionError):
        await factory.open_call("call-11")
    assert mcp.closed


class FakeSlowSession:
    """A session whose plan takes a while, so the caller can be cancelled meanwhile."""

    def __init__(self, gate: threading.Event) -> None:
        self.gate = gate
        self.closed = False

    def start_plan(self, tool_calls: list[dict[str, object]], goal: str | None = None) -> None:
        self.gate.wait(5)

    def close(self) -> None:
        self.closed = True


async def test_cancelled_open_call_closes_mcp_and_the_late_armoriq_session() -> None:
    mcp = FakeMCP()
    gate, opened = threading.Event(), threading.Event()
    sessions: list[FakeSlowSession] = []

    def slow_session(email: str) -> FakeSlowSession:
        sessions.append(FakeSlowSession(gate))
        opened.set()
        return sessions[-1]

    async def connect() -> FakeMCP:
        return mcp

    async def enforcer(tool_names: list[str]) -> ArmorIQEnforcer:
        return ArmorIQEnforcer(
            session_factory=slow_session,  # type: ignore[arg-type]
            approvals=FakeApprovals(),
            tool_names=tool_names,
            poll_seconds=0.01,
            plan_executor=ThreadPoolExecutor(max_workers=1),
        )

    factory = GovernedGatewayFactory(
        settings(), executor_factory=connect, enforcer_factory=enforcer
    )
    task = asyncio.create_task(factory.open_call("call-12"))
    assert await asyncio.to_thread(opened.wait, 5)  # the plan is now being opened
    task.cancel()  # the caller hangs up while the plan is still being opened
    with pytest.raises(asyncio.CancelledError):
        await task
    assert mcp.closed
    gate.set()  # the plan finishes after the hang-up
    for _ in range(100):  # closed from a worker thread shortly after
        if sessions[0].closed:
            break
        await asyncio.sleep(0.01)
    assert sessions[0].closed
