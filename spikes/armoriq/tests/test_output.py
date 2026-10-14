"""Full printed output must never contain a real identity or a credential."""

from __future__ import annotations

import logging
from collections.abc import Iterator
from typing import Any

import pytest
from armoriq_spike.output import MaskedOutput, install_masked_logging
from armoriq_spike.sequence import CallRecord, governed_call

GUEST = "real.person+guest@example.org"
ADMIN = "real.person@example.org"


@pytest.fixture
def out() -> MaskedOutput:
    o = MaskedOutput({GUEST: "<guest>", ADMIN: "<admin>"})
    o.add("Real Person's Workspace", "<org>")
    return o


def test_show_masks_title_and_payload_and_redacts_keys(
    out: MaskedOutput, capsys: pytest.CaptureFixture[str]
) -> None:
    out.show(
        f"resolve-user guest = {GUEST}",
        {"user": {"email": GUEST}, "org": {"name": "Real Person's Workspace"}, "apiKey": "x"},
    )
    printed = capsys.readouterr().out
    assert "real.person" not in printed
    assert "Real Person" not in printed
    assert "resolve-user guest = <guest>" in printed
    assert '"apiKey": "<redacted>"' in printed


def test_record_line_masks_user_and_reason(
    out: MaskedOutput, capsys: pytest.CaptureFixture[str]
) -> None:
    record = CallRecord(
        tool="issue_refund",
        user_email=GUEST,
        decision="hold",
        outcome="error",
        reason=f"403 for {ADMIN}",
    )
    out.print_record("HOLD", record)
    printed = capsys.readouterr().out
    assert "real.person" not in printed
    assert "user=<guest>" in printed
    assert "403 for <admin>" in printed


@pytest.fixture
def restore_root_logging() -> Iterator[None]:
    root = logging.getLogger()
    handlers, level = root.handlers[:], root.level
    yield
    root.handlers[:] = handlers
    root.setLevel(level)


@pytest.mark.usefixtures("restore_root_logging")
async def test_logged_exceptions_and_tracebacks_are_masked_on_stderr(
    out: MaskedOutput, capsys: pytest.CaptureFixture[str]
) -> None:
    out.add("ak_live_fakefakefake", "<api-key>")
    install_masked_logging(out)

    class SessionThatLeaks:
        """Fake SDK session whose error echoes an identity and a key, as httpx errors can."""

        def start_plan(self, tool_calls: list[dict[str, Any]], goal: str | None = None) -> None:
            raise RuntimeError(f"401 for {GUEST} with X-API-Key ak_live_fakefakefake")

    async def never(tool: str, args: dict[str, Any]) -> None:
        raise AssertionError("must not run")

    record = await governed_call(
        SessionThatLeaks(),  # type: ignore[arg-type]  # only start_plan is reached
        approvals=None,  # type: ignore[arg-type]  # never reached: the plan fails first
        tool_name="issue_refund",
        args={},
        user_email=GUEST,
        goal="g",
        execute=never,
        approval_wait_seconds=1,
        approval_poll_seconds=0.01,
    )
    captured = capsys.readouterr()
    assert record.outcome == "error"
    assert "Traceback" in captured.err  # the traceback was logged...
    assert "<guest>" in captured.err  # ...and masked
    assert "<api-key>" in captured.err
    assert "real.person" not in captured.err + captured.out
    assert "ak_live_fakefakefake" not in captured.err + captured.out


@pytest.mark.usefixtures("restore_root_logging")
def test_probe_identity_is_masked_in_records_logs_and_evidence(
    out: MaskedOutput, capsys: pytest.CaptureFixture[str]
) -> None:
    stranger = "someone.else@example.net"
    assert out.register_identity(stranger) == stranger
    install_masked_logging(out)
    record = CallRecord(tool="get_hotel_info", user_email=stranger, decision="allow", outcome="ran")

    out.print_record("PROBE", record)
    logging.getLogger("armoriq.test").warning("enforce failed for %s", stranger)
    evidence = out.clean({"records": [record.model_dump()]})  # what save_evidence writes

    captured = capsys.readouterr()
    assert stranger not in captured.out + captured.err + str(evidence)
    assert "user=<probe-user>" in captured.out
    assert "<probe-user>" in captured.err
    assert evidence["records"][0]["user_email"] == "<probe-user>"


def test_register_identity_keeps_a_configured_placeholder(out: MaskedOutput) -> None:
    out.register_identity(GUEST.upper())
    assert out.clean(GUEST) == "<guest>"


def test_unset_secrets_never_mask_ordinary_text(out: MaskedOutput) -> None:
    # secret_mask() yields "" keys when the MCP token or JWT is unset; they must be inert.
    out.mask.update({"": "<jwt>"})
    assert out.clean("plain text x") == "plain text x"


def test_add_ignores_empty_values(out: MaskedOutput) -> None:
    out.add(None, "<org>")
    out.add("", "<org>")
    assert "" not in out.mask
