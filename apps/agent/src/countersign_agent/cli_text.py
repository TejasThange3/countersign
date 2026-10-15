"""Text-mode REPL that drives one governed phone call by typing tool calls.

    uv run --project apps/agent python -m countersign_agent.cli_text

Commands:
    specs                         list the tools the LLM would see (guest_id hidden)
    verify <booking_ref> <last>   verify_guest shortcut
    call <tool> [json-args]       e.g. call issue_refund {"booking_id": 3, "amount": 40, "reason": "x"}
    wait [seconds]                wait for the last held call to be approved (default 60)
    quit

Everything printed goes through the bridge's Masker: no identity emails, guest emails or keys.
Uses the real .env: live ArmorIQ unless DISABLE_ARMORIQ=1.
"""

from __future__ import annotations

import asyncio
import json
import shlex
import uuid

from countersign_agent.bridge import GovernedGateway, GovernedGatewayFactory
from countersign_agent.bridge.masking import install_masked_logging
from countersign_agent.contracts import GatewayEvent, Outcome, ToolResult

HELP = __doc__ or ""


async def run() -> None:
    factory = GovernedGatewayFactory()
    install_masked_logging(factory.masker)

    async def show_event(event: GatewayEvent) -> None:
        print(f"  [event] {event.kind} {json.dumps(event.data, default=str)}")

    gateway = await factory.open_call(f"cli-{uuid.uuid4().hex[:8]}", events=show_event)
    print(f"call {gateway.call_id} open, armoriq_mode={gateway.mode}. Type 'help'.")
    last_held: ToolResult | None = None
    try:
        while True:
            line = (await asyncio.to_thread(input, "> ")).strip()
            if not line:
                continue
            cmd, _, rest = line.partition(" ")
            if cmd in {"quit", "exit"}:
                break
            if cmd == "help":
                print(HELP)
            elif cmd == "specs":
                for spec in gateway.tool_specs():
                    params = ", ".join(spec.parameters.get("properties", {}))
                    print(f"  {spec.tier:9} {spec.name}({params})")
            elif cmd in {"verify", "call", "wait"}:
                try:
                    result = await _dispatch(gateway, cmd, rest, last_held)
                except ValueError as exc:
                    print(f"  usage error: {exc}")
                    continue
                if result.outcome is Outcome.PENDING:
                    last_held = result
                elif last_held is not None and result.delegation_id == last_held.delegation_id:
                    last_held = None
                print(json.dumps(factory.masker.clean(result.model_dump(mode="json")), indent=2))
            else:
                print("  unknown command; type 'help'")
    except (EOFError, KeyboardInterrupt):
        pass
    finally:
        await gateway.close()


async def _dispatch(
    gateway: GovernedGateway, cmd: str, rest: str, last_held: ToolResult | None
) -> ToolResult:
    if cmd == "verify":
        parts = shlex.split(rest)
        if len(parts) != 2:
            raise ValueError("verify <booking_ref> <last_name>")
        return await gateway.call("verify_guest", {"booking_ref": parts[0], "last_name": parts[1]})
    if cmd == "call":
        name, _, raw = rest.strip().partition(" ")
        if not name:
            raise ValueError("call <tool> [json-args]")
        try:
            args = json.loads(raw) if raw.strip() else {}
        except json.JSONDecodeError as exc:
            raise ValueError(f"arguments are not JSON: {exc}") from exc
        if not isinstance(args, dict):
            raise ValueError("arguments must be a JSON object")
        return await gateway.call(name, args)
    if last_held is None:
        raise ValueError("no held call to wait for")
    timeout = float(rest) if rest.strip() else 60.0
    print(f"  waiting up to {timeout:.0f}s for an approver...")
    return await gateway.wait(last_held, timeout_s=timeout)


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
