"""Hotel MCP server (FastMCP): front-desk tools backed by Postgres, governed by ArmorIQ."""


def main() -> None:
    from hotel_mcp.cli import main as cli_main

    cli_main()
