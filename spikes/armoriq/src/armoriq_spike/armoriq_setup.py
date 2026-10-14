"""Client and session construction, copied from the Strands factory (integrations/strands.py).

ArmorIQStrands builds one client per process, bootstraps once, derives a tool-name parser from
the bootstrap `toolMap`, then per user calls client.for_user(email).start_session(mode="sdk").
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from armoriq_sdk import ArmorIQClient
from armoriq_sdk.session import ArmorIQSession, SessionOptions

from armoriq_spike.settings import SpikeSettings

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


def build_client(settings: SpikeSettings) -> ArmorIQClient:
    # agent_id is the registered agent name; the SDK otherwise sends a "__sdk_multiuser__" placeholder.
    return ArmorIQClient(api_key=settings.require_api_key(), agent_id=settings.armoriq_agent_name)


def start_user_session(
    client: ArmorIQClient, bootstrap: Mapping[str, Any], settings: SpikeSettings, user_email: str
) -> ArmorIQSession:
    return client.for_user(user_email).start_session(
        SessionOptions(
            mode="sdk",
            validity_seconds=3600,
            tool_name_parser=make_tool_name_parser(bootstrap, settings.armoriq_mcp_name),
            default_mcp_name=settings.armoriq_mcp_name,
        )
    )
