"""The MCP surface the agent sees: tool names, tiers, schemas and errors (in-memory client)."""

from collections.abc import AsyncIterator
from typing import Any

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError
from hotel_mcp.server import build_server
from hotel_mcp.services import BOOKING_NOT_FOUND
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tests.conftest import TODAY
from tests.scoping import BOOKING_SCOPED_TOOLS

TIERS = {
    "read": {
        "verify_guest",
        "get_booking",
        "check_availability",
        "get_hotel_info",
        "get_cancellation_policy",
    },
    "write": {
        "create_booking",
        "modify_booking_dates",
        "add_booking_note",
        "request_housekeeping",
        "cancel_own_booking",
    },
    "money": {"issue_refund", "apply_comp_credit", "waive_fee"},
    "sensitive": {
        "export_guest_list",
        "cancel_any_booking",
        "delete_guest_profile",
        "grant_staff_access",
    },
}
GUEST_SCOPED = (TIERS["read"] | TIERS["write"] | TIERS["money"]) - {
    "verify_guest",
    "check_availability",
    "get_hotel_info",
    "get_cancellation_policy",
}


@pytest.fixture
async def client(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> AsyncIterator[Client]:
    async with Client(build_server(sessionmaker, today=lambda: TODAY)) as c:
        yield c


async def _tools(client: Client) -> dict[str, Any]:
    return {t.name: t for t in await client.list_tools()}


async def test_every_scope_tool_exists_with_its_tier_tag(client: Client) -> None:
    tools = await _tools(client)
    assert set(tools) == set().union(*TIERS.values())
    for tier, names in TIERS.items():
        for name in names:
            assert tools[name].meta["fastmcp"]["tags"] == [tier], name
            assert tools[name].description, f"{name} needs a docstring the model can read"


async def test_money_tools_take_amount_in_dollars_and_reason(client: Client) -> None:
    tools = await _tools(client)
    for name in TIERS["money"]:
        schema = tools[name].input_schema
        assert schema["properties"]["amount"]["type"] == "number"
        assert set(schema["required"]) == {"guest_id", "booking_id", "amount", "reason"}


async def test_guest_scoped_tools_require_guest_id_and_others_do_not(client: Client) -> None:
    tools = await _tools(client)
    for name, tool in tools.items():
        props = tool.input_schema.get("properties", {})
        if name in GUEST_SCOPED:
            assert "guest_id" in tool.input_schema["required"], name
        else:
            # Sensitive tools name their target differently so bridge injection can't redirect it.
            assert "guest_id" not in props, name


async def test_verify_guest_structured_result_shape(client: Client) -> None:
    """The bridge reads `guest_id` from this result to switch identity; keep it stable."""
    ok = await client.call_tool("verify_guest", {"booking_ref": "LRK-1001", "last_name": "Okafor"})
    data = ok.structured_content
    assert data is not None
    assert data["verified"] is True
    assert isinstance(data["guest_id"], int)
    assert data["bookings"]
    assert set(data["bookings"][0]) >= {"booking_id", "ref", "check_in", "check_out", "status"}
    assert "LRK-1001" in {b["ref"] for b in data["bookings"]}

    bad = await client.call_tool("verify_guest", {"booking_ref": "LRK-1001", "last_name": "Nope"})
    assert bad.structured_content == {
        "verified": False,
        "guest_id": None,
        "first_name": None,
        "bookings": [],
    }


async def _ids(client: Client) -> tuple[int, int, int]:
    a = (
        await client.call_tool("verify_guest", {"booking_ref": "LRK-1001", "last_name": "Okafor"})
    ).structured_content
    b = (
        await client.call_tool("verify_guest", {"booking_ref": "LRK-1002", "last_name": "Brandt"})
    ).structured_content
    assert a is not None and b is not None
    return a["guest_id"], a["bookings"][0]["booking_id"], b["bookings"][0]["booking_id"]


@pytest.mark.parametrize("tool", sorted(BOOKING_SCOPED_TOOLS))
async def test_booking_scoped_tool_rejects_other_guests_booking(client: Client, tool: str) -> None:
    guest_a, _, booking_b = await _ids(client)
    args = {"guest_id": guest_a, "booking_id": booking_b, **BOOKING_SCOPED_TOOLS[tool]}
    with pytest.raises(ToolError) as exc:
        await client.call_tool(tool, args)
    assert str(exc.value) == BOOKING_NOT_FOUND


async def test_booking_scoped_tool_list_covers_every_scoped_tool(client: Client) -> None:
    tools = await _tools(client)
    with_booking = {
        n for n, t in tools.items() if "booking_id" in t.input_schema.get("required", [])
    }
    assert with_booking - {"cancel_any_booking"} == set(BOOKING_SCOPED_TOOLS)


@pytest.mark.parametrize("tool", sorted(BOOKING_SCOPED_TOOLS))
async def test_booking_scoped_tool_works_on_own_booking(client: Client, tool: str) -> None:
    guest_a, booking_a, _ = await _ids(client)
    args = {"guest_id": guest_a, "booking_id": booking_a, **BOOKING_SCOPED_TOOLS[tool]}
    result = await client.call_tool(tool, args)
    assert result.structured_content is not None


async def test_amount_must_be_positive_at_schema_level(client: Client) -> None:
    guest_a, booking_a, _ = await _ids(client)
    with pytest.raises(ToolError):
        await client.call_tool(
            "issue_refund",
            {"guest_id": guest_a, "booking_id": booking_a, "amount": -10, "reason": "x"},
        )


async def test_static_info_tools(client: Client) -> None:
    info = await client.call_tool("get_hotel_info", {})
    assert info.structured_content is not None
    assert info.structured_content["name"] == "The Larkspur"
    policy = await client.call_tool("get_cancellation_policy", {})
    assert "48 hours" in str(policy.data)
