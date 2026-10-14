"""Live ArmorIQ smoke test (calls the real ArmorIQ; never run by scripts/check.py).

Start the toy server first (and the cloudflared tunnel if ArmorIQ needs to reach it):
    uv run --project spikes/armoriq python -m armoriq_spike.toy_server

Then:
    uv run --project spikes/armoriq python spikes/armoriq/smoke.py preflight
    uv run --project spikes/armoriq python spikes/armoriq/smoke.py run
    uv run --project spikes/armoriq python spikes/armoriq/smoke.py probe <tool> [--as EMAIL] [--label L]
    uv run --project spikes/armoriq python spikes/armoriq/smoke.py approve-test [--cred api_key|jwt]
    uv run --project spikes/armoriq python spikes/armoriq/smoke.py reject <delegation_id>

Every run writes its records to spikes/armoriq/evidence/ with armoriq_mode="live". `run` and
`approve-test` exit nonzero (after saving evidence) unless every case did what it should.
Everything printed or saved passes through MaskedOutput: no credentials, no real identities.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path
from typing import Any

import httpx
from armoriq_sdk import ArmorIQClient
from armoriq_spike.approval import CheckedApprovals
from armoriq_spike.armoriq_setup import build_client, start_user_session
from armoriq_spike.delegation import (
    ApproverRole,
    DelegationDecisionResult,
    decide_delegation,
    fetch_approver_role,
)
from armoriq_spike.expectations import Expected, mismatches
from armoriq_spike.output import MaskedOutput, install_masked_logging
from armoriq_spike.sequence import CallRecord, governed_call
from armoriq_spike.settings import SpikeSettings
from fastmcp import Client

EVIDENCE_DIR = Path(__file__).resolve().parent / "evidence"
GOAL = "Countersign Day 1 smoke test (synthetic guest booking b-1001)"
REFUND_ARGS = {"booking_id": "b-1001", "amount": 250, "reason": "smoke test"}
# Default args per toy tool, so `probe <tool>` sends a valid call.
TOOL_ARGS: dict[str, dict[str, Any]] = {"issue_refund": REFUND_ARGS}

OnHold = Callable[[CallRecord], Awaitable[None]]
# Filled in main() from .env; preflight adds the org name. One instance for the whole CLI run.
OUT = MaskedOutput({})


def save_evidence(kind: str, payload: dict[str, Any]) -> Path:
    EVIDENCE_DIR.mkdir(exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    path = EVIDENCE_DIR / f"{stamp}-{kind}.json"
    body = {
        "armoriq_mode": "live",
        "sdk_version": version("armoriq-sdk"),
        "recorded_at": stamp,
        **payload,
    }
    path.write_text(json.dumps(OUT.clean(body), indent=2, default=str), encoding="utf-8")
    return path


def fail_on_mismatch(cases: list[tuple[Expected, CallRecord]]) -> None:
    problems = mismatches(cases)
    if problems:
        for problem in problems:
            print(OUT.clean(f"MISMATCH: {problem}"))
        raise SystemExit(1)
    print("all cases matched their expected decision and outcome")


def mcp_executor(settings: SpikeSettings):
    url = f"http://127.0.0.1:{settings.spike_mcp_port}/mcp"
    token = settings.require_mcp_token()  # never call the MCP server unauthenticated

    async def execute(tool_name: str, args: dict[str, Any]) -> Any:
        # The bridge, not ArmorIQ, calls the MCP server in sdk mode.
        async with Client(url, auth=token) as mcp:
            result = await mcp.call_tool(tool_name, args)
            return result.structured_content or [str(c) for c in result.content]

    return execute


async def wait_for_console_approval(record: CallRecord) -> None:
    print(
        f"\n>>> HELD: {record.tool} (delegation {record.delegation_id}). Approve or reject it on "
        "platform.armoriq.ai -> Intent -> Held Actions -> 'Needs you'. Waiting...",
        flush=True,
    )


async def connect(settings: SpikeSettings) -> tuple[ArmorIQClient, dict[str, Any]]:
    # Both are blocking HTTP (key check, bootstrap): off the event loop, like every SDK call.
    client = await asyncio.to_thread(build_client, settings)
    bootstrap = await asyncio.to_thread(client.bootstrap)
    return client, bootstrap


async def call(
    client: ArmorIQClient,
    bootstrap: dict[str, Any],
    settings: SpikeSettings,
    user: str,
    tool: str,
    args: dict[str, Any],
    *,
    on_hold: OnHold = wait_for_console_approval,
    approval_wait_seconds: float | None = None,
) -> CallRecord:
    session = await asyncio.to_thread(start_user_session, client, bootstrap, settings, user)
    return await governed_call(
        session,
        approvals=CheckedApprovals(client),  # fails closed if mark-executed is refused
        tool_name=tool,
        args=args,
        user_email=user,
        goal=GOAL,
        execute=mcp_executor(settings),
        approval_wait_seconds=approval_wait_seconds or settings.approval_wait_seconds,
        approval_poll_seconds=settings.approval_poll_seconds,
        on_hold=on_hold,
    )


def cmd_preflight(settings: SpikeSettings) -> None:
    client = build_client(settings)
    print(f"API key loaded ({len(settings.require_api_key())} chars, value not shown)")
    print(f"backend endpoint: {client.backend_endpoint}")
    bootstrap = client.bootstrap()
    OUT.add((bootstrap.get("org") or {}).get("name"), "<org>")
    OUT.show("bootstrap (POST /iap/sdk/bootstrap)", bootstrap)
    users = {
        "unverified": settings.armoriq_user_unverified,
        "guest": settings.armoriq_user_guest,
        "manager": settings.armoriq_user_manager,
    }
    resolved: dict[str, Any] = {}
    for label, email in users.items():
        try:
            resolved[label] = client.resolve_user(email)
        except Exception as exc:
            resolved[label] = {"error": str(exc)}
        OUT.show(f"resolve-user {label} = {email}", resolved[label])
    save_evidence("preflight", {"bootstrap": bootstrap, "resolve_user": resolved})


async def cmd_run(settings: SpikeSettings) -> None:
    client, bootstrap = await connect(settings)
    guest = settings.armoriq_user_guest
    plan: list[tuple[Expected, str, dict[str, Any]]] = [
        ("ALLOW", "get_hotel_info", {}),
        ("HOLD", "issue_refund", REFUND_ARGS),
        ("BLOCK", "export_guest_list", {}),
    ]
    cases: list[tuple[Expected, CallRecord]] = []
    for expected, tool, args in plan:
        record = await call(client, bootstrap, settings, guest, tool, args)
        OUT.print_record(expected, record)
        cases.append((expected, record))
    records = [{"expected": e, **r.model_dump()} for e, r in cases]
    print(f"\nevidence: {save_evidence('run', {'records': records})}")
    fail_on_mismatch(cases)


async def cmd_probe(settings: SpikeSettings, tool: str, user: str, label: str) -> None:
    client, bootstrap = await connect(settings)
    record = await call(client, bootstrap, settings, user, tool, TOOL_ARGS.get(tool, {}))
    OUT.print_record(label.upper(), record)
    print(f"\nevidence: {save_evidence(label, {'records': [record.model_dump()]})}")


async def cmd_approve_test(settings: SpikeSettings, cred: str, approver: str) -> None:
    """Raise one fresh hold, approve it over HTTP with ONE credential, and let the normal
    approval poll observe the result. One credential per run keeps the live key light.
    A credential the API refuses (the hold then times out) counts as a failure: exit 1."""
    if cred == "jwt":
        jwt = settings.armoriq_dashboard_jwt.get_secret_value()
        if not jwt:
            raise SystemExit("ARMORIQ_DASHBOARD_JWT is empty in .env")
        headers = {"Authorization": f"Bearer {jwt}"}
    else:
        headers = {"X-API-Key": settings.require_api_key()}

    client, bootstrap = await connect(settings)
    decisions: list[DelegationDecisionResult] = []
    roles: list[ApproverRole] = []

    async def approve_over_http(record: CallRecord) -> None:
        if not record.delegation_id:  # governed_call only calls on_hold with an id
            raise RuntimeError("hold without a delegation id")
        async with httpx.AsyncClient() as http:
            # Declare the approver's real role and limit, read the way the SDK reads them.
            role = await fetch_approver_role(
                http, client.backend_endpoint, {"X-API-Key": settings.require_api_key()}, approver
            )
            roles.append(role)
            result = await decide_delegation(
                http,
                client.backend_endpoint,
                record.delegation_id,
                headers,
                approver,
                approver=role,
            )
        decisions.append(result)
        OUT.show(f"POST /delegation/approve with {cred} -> HTTP {result.status_code}", result.body)

    # 30 s is plenty when the HTTP approval works; when it fails we only need the timeout.
    record = await call(
        client,
        bootstrap,
        settings,
        settings.armoriq_user_guest,
        "issue_refund",
        REFUND_ARGS,
        on_hold=approve_over_http,
        approval_wait_seconds=30,
    )
    OUT.print_record(f"APPROVE-TEST {cred}", record)
    evidence = {
        "credential": cred,
        "approver_email": approver,
        "declared_roles": [r.model_dump() for r in roles],
        "decisions": [d.model_dump() for d in decisions],
        "records": [record.model_dump()],
    }
    print(f"\nevidence: {save_evidence(f'approve-test-{cred}', evidence)}")
    fail_on_mismatch([("APPROVED", record)])


async def cmd_reject(settings: SpikeSettings, delegation_id: str, approver: str) -> None:
    """POST /delegation/reject; the approver's role is recorded, but reject takes no limit."""
    backend = (await asyncio.to_thread(build_client, settings)).backend_endpoint
    headers = {"X-API-Key": settings.require_api_key()}
    async with httpx.AsyncClient() as http:
        role = await fetch_approver_role(http, backend, headers, approver)
        result = await decide_delegation(
            http, backend, delegation_id, headers, approver, "reject", approver=role
        )
    OUT.show(f"POST /delegation/reject -> HTTP {result.status_code}", result.body)
    evidence = {
        "delegation_id": delegation_id,
        "approver_email": approver,
        "declared_roles": [role.model_dump()],
        "decisions": [result.model_dump()],
    }
    print(f"\nevidence: {save_evidence('reject-test', evidence)}")
    if not result.ok:
        raise SystemExit(1)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("preflight", help="check the key, bootstrap and resolve the three identities")
    sub.add_parser("run", help="ALLOW, HOLD (wait for approval) and BLOCK as the guest identity")
    probe = sub.add_parser("probe", help="one governed call to any tool, as any identity")
    probe.add_argument("tool")
    probe.add_argument("--as", dest="user", default=None, help="for_user email (default: guest)")
    probe.add_argument("--label", default="probe", help="label for output and evidence file")
    approve = sub.add_parser("approve-test", help="raise a hold and approve it over HTTP")
    approve.add_argument("--cred", choices=["api_key", "jwt"], default="api_key")
    # admin by default: the manager alias is not an org member, so its approval limit is 0.
    approve.add_argument("--approver", choices=["admin", "manager"], default="admin")
    reject = sub.add_parser("reject", help="reject an existing held delegation over HTTP")
    reject.add_argument("delegation_id")
    reject.add_argument("--approver", choices=["admin", "manager"], default="admin")
    args = parser.parse_args()

    settings = SpikeSettings()
    OUT.mask.update(settings.identity_mask())
    OUT.mask.update(settings.secret_mask())
    install_masked_logging(OUT)
    logging.captureWarnings(True)  # warnings go through the masked handler too
    try:
        dispatch(args, settings)
    except Exception:
        # Python's default excepthook would print an unmasked traceback (SDK and httpx errors
        # can quote emails or headers); log it through the masked handler instead.
        logging.getLogger("smoke").exception("smoke command failed")
        raise SystemExit(1) from None


def dispatch(args: argparse.Namespace, settings: SpikeSettings) -> None:
    if args.cmd == "preflight":
        cmd_preflight(settings)
    elif args.cmd == "run":
        asyncio.run(cmd_run(settings))
    elif args.cmd == "probe":
        user = OUT.register_identity(args.user or settings.armoriq_user_guest)
        asyncio.run(cmd_probe(settings, args.tool, user, args.label))
    elif args.cmd in ("approve-test", "reject"):
        approver = (
            settings.armoriq_admin_email
            if args.approver == "admin"
            else settings.armoriq_user_manager
        )
        if args.cmd == "approve-test":
            asyncio.run(cmd_approve_test(settings, args.cred, approver))
        else:
            asyncio.run(cmd_reject(settings, args.delegation_id, approver))


if __name__ == "__main__":
    main()
