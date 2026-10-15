"""Client and session construction, copied from the Strands factory (integrations/strands.py)
via spikes/armoriq. One client per process; one session per identity per phone call, in sdk
mode (ArmorIQ decides, the bridge runs the tool, then reports).

Everything here is blocking HTTP: callers run it in `asyncio.to_thread`.
"""

from __future__ import annotations

from collections.abc import Callable

from armoriq_sdk import ArmorIQClient
from armoriq_sdk.session import ArmorIQSession, SessionOptions

from countersign_agent.bridge.settings import BridgeSettings

ToolNameParser = Callable[[str], tuple[str, str]]


def make_tool_name_parser(mcp_name: str) -> ToolNameParser:
    """Every tool belongs to the one MCP the bridge talks to (ARMORIQ_MCP_NAME).

    Strands looks the tool up in bootstrap's `toolMap` first, but that map is flat
    (tool -> one MCP): when two registered MCPs share a tool name (a leftover test server
    next to hotel-mcp), it can name the wrong server. The plan step's `mcp` is what the
    audit and the in-plan check use, so it is pinned here instead.
    """

    def parse(tool_name: str) -> tuple[str, str]:
        return (mcp_name, tool_name)

    return parse


def build_client(settings: BridgeSettings) -> ArmorIQClient:
    """The constructor checks the key over HTTP."""
    # agent_id is the registered agent name; the SDK otherwise sends a "__sdk_multiuser__"
    # placeholder.
    return ArmorIQClient(api_key=settings.require_api_key(), agent_id=settings.armoriq_agent_name)


def start_user_session(
    client: ArmorIQClient, settings: BridgeSettings, user_email: str
) -> ArmorIQSession:
    return client.for_user(user_email).start_session(
        SessionOptions(
            mode="sdk",
            validity_seconds=settings.armoriq_session_validity_seconds,
            tool_name_parser=make_tool_name_parser(settings.armoriq_mcp_name),
            default_mcp_name=settings.armoriq_mcp_name,
        )
    )
