"""Client and session construction, copied from the Strands factory (integrations/strands.py)
via spikes/armoriq. One client per process, bootstrapped once; one session per identity per
phone call, in sdk mode (ArmorIQ decides, the bridge runs the tool, then reports).

Everything here is blocking HTTP: callers run it in `asyncio.to_thread`.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from armoriq_sdk import ArmorIQClient
from armoriq_sdk.session import ArmorIQSession, SessionOptions

from countersign_agent.bridge.settings import BridgeSettings

ToolNameParser = Callable[[str], tuple[str, str]]


def make_tool_name_parser(bootstrap: Mapping[str, Any], default_mcp: str) -> ToolNameParser:
    """Same resolution order as ArmorIQStrands._tool_name_parser: toolMap, then `mcp__tool`,
    then the default MCP name."""
    tool_map: Mapping[str, str] = bootstrap.get("toolMap") or {}

    def parse(tool_name: str) -> tuple[str, str]:
        mcp = tool_map.get(tool_name)
        if mcp:
            return (mcp, tool_name)
        if "__" in tool_name:
            prefix, action = tool_name.split("__", 1)
            return (prefix, action)
        return (default_mcp, tool_name)

    return parse


def build_client(settings: BridgeSettings) -> tuple[ArmorIQClient, dict[str, Any]]:
    """The constructor checks the key over HTTP; bootstrap fetches the tool map."""
    # agent_id is the registered agent name; the SDK otherwise sends a "__sdk_multiuser__"
    # placeholder.
    client = ArmorIQClient(api_key=settings.require_api_key(), agent_id=settings.armoriq_agent_name)
    return client, client.bootstrap() or {}


def start_user_session(
    client: ArmorIQClient,
    bootstrap: Mapping[str, Any],
    settings: BridgeSettings,
    user_email: str,
) -> ArmorIQSession:
    return client.for_user(user_email).start_session(
        SessionOptions(
            mode="sdk",
            validity_seconds=settings.armoriq_session_validity_seconds,
            tool_name_parser=make_tool_name_parser(bootstrap, settings.armoriq_mcp_name),
            default_mcp_name=settings.armoriq_mcp_name,
        )
    )
