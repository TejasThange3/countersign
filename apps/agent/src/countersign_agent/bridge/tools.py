"""hotel-mcp tools as the bridge and the LLM see them.

The tier comes from the tool's FastMCP tag (`read`, `write`, `money`, `sensitive`). The
identity argument `guest_id` is removed from every schema the LLM sees: the bridge fills it in
from verification (product rule 3). `target_guest_id` is a different argument on purpose and is
left alone, so ArmorIQ is what stops the sensitive tools.
"""

from __future__ import annotations

import copy
from typing import Any, Literal, cast, get_args

from pydantic import BaseModel

from countersign_agent.contracts import ToolSpec

Tier = Literal["read", "write", "money", "sensitive"]
TIERS: tuple[Tier, ...] = get_args(Tier)
IDENTITY_ARG = "guest_id"


class ToolInfo(BaseModel):
    """One entry of MCP `tools/list`, reduced to what the bridge needs."""

    name: str
    description: str = ""
    input_schema: dict[str, Any]
    tags: list[str] = []


class BridgeTool(BaseModel):
    spec: ToolSpec
    needs_guest_id: bool


def tier_of(tags: list[str]) -> Tier | None:
    """Exactly one known tier tag, or None: a tool we can't place is never offered."""
    found = [t for t in tags if t in TIERS]
    return cast(Tier, found[0]) if len(found) == 1 else None


def strip_identity(schema: dict[str, Any]) -> dict[str, Any]:
    """Copy of `schema` without `guest_id` in `properties` or `required`."""
    out = copy.deepcopy(schema)
    props = out.get("properties")
    if isinstance(props, dict):
        props.pop(IDENTITY_ARG, None)
    required = out.get("required")
    if isinstance(required, list):
        out["required"] = [r for r in required if r != IDENTITY_ARG]
    return out


def to_bridge_tool(info: ToolInfo) -> BridgeTool | None:
    tier = tier_of(info.tags)
    if tier is None:
        return None
    props = info.input_schema.get("properties") or {}
    return BridgeTool(
        spec=ToolSpec(
            name=info.name,
            description=info.description,
            parameters=strip_identity(info.input_schema),
            tier=tier,
        ),
        needs_guest_id=IDENTITY_ARG in props,
    )


def convert_tools(infos: list[ToolInfo]) -> dict[str, BridgeTool]:
    """Tools without a single known tier tag are dropped (fail closed)."""
    tools = {}
    for info in infos:
        tool = to_bridge_tool(info)
        if tool is not None:
            tools[info.name] = tool
    return tools
