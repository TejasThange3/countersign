from armoriq_spike.armoriq_setup import make_tool_name_parser


def test_tool_map_wins() -> None:
    parse = make_tool_name_parser({"toolMap": {"issue_refund": "hotel-mcp"}}, "default-mcp")
    assert parse("issue_refund") == ("hotel-mcp", "issue_refund")


def test_double_underscore_prefix_names_the_mcp() -> None:
    parse = make_tool_name_parser({}, "default-mcp")
    assert parse("other-mcp__get_hotel_info") == ("other-mcp", "get_hotel_info")


def test_falls_back_to_default_mcp() -> None:
    parse = make_tool_name_parser({"toolMap": None}, "hotel-mcp")
    assert parse("get_hotel_info") == ("hotel-mcp", "get_hotel_info")
