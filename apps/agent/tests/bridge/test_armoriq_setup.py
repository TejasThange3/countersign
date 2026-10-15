from countersign_agent.bridge.armoriq_setup import make_tool_name_parser


def test_every_tool_is_pinned_to_the_configured_mcp() -> None:
    # Even a tool a leftover test server also registers goes to the configured MCP.
    parse = make_tool_name_parser("hotel-mcp-2")
    assert parse("issue_refund") == ("hotel-mcp-2", "issue_refund")
    assert parse("verify_guest") == ("hotel-mcp-2", "verify_guest")
