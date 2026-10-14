"""Toy FastMCP server for the ArmorIQ smoke test.

Tool names match the real hotel-mcp tiers (scope section 4) so the policies written for this
spike carry over to the real server unchanged:

    get_hotel_info        read tier         -> expected ALLOW
    issue_refund          money tier        -> expected ALLOW up to $100, HOLD above
    export_guest_list     sensitive tier    -> expected BLOCK
    spike_uncovered_probe no policy at all  -> what ArmorIQ does here is a Day 1 question

No permission logic lives here (AGENTS.md rule 2). Every inbound HTTP request is logged with
its user agent and source so we can see whether ArmorIQ ever contacts this URL in sdk mode.

Run:  uv run --project spikes/armoriq python -m armoriq_spike.toy_server
"""

from __future__ import annotations

import logging
from typing import Any

import uvicorn
from fastmcp import FastMCP
from fastmcp.server.auth.providers.jwt import StaticTokenVerifier
from starlette.types import ASGIApp, Receive, Scope, Send

from armoriq_spike.settings import SpikeSettings

logger = logging.getLogger("toy_server")


def build_server(bearer_token: str) -> FastMCP:
    # A static bearer token stands in for the credential registered with ArmorIQ. No token, no
    # server: through the public tunnel an open server would let anyone skip ArmorIQ entirely.
    if not bearer_token:
        raise ValueError("MCP_BEARER_TOKEN is empty; refusing to serve tools without auth")
    auth = StaticTokenVerifier(tokens={bearer_token: {"client_id": "armoriq", "scopes": []}})
    mcp = FastMCP("hotel-mcp", auth=auth)

    @mcp.tool
    def get_hotel_info() -> dict[str, Any]:
        """Public facts about the hotel: name, check-in and check-out times."""
        return {"name": "The Larkspur (synthetic)", "check_in": "15:00", "check_out": "11:00"}

    @mcp.tool
    def issue_refund(booking_id: str, amount: float, reason: str) -> dict[str, Any]:
        """Record a refund for a booking. Synthetic: no payment provider is called."""
        return {
            "refund_id": f"rf-{booking_id}",
            "booking_id": booking_id,
            "amount": amount,
            "reason": reason,
        }

    @mcp.tool
    def export_guest_list() -> dict[str, Any]:
        """Export every guest record. Sensitive: policy should block this."""
        return {"guests": ["synthetic-guest-1", "synthetic-guest-2"]}

    @mcp.tool
    def spike_uncovered_probe() -> dict[str, Any]:
        """Deliberately covered by no policy, to observe ArmorIQ's default action."""
        return {"probe": "ran"}

    return mcp


class RequestLogMiddleware:
    """Logs who calls the server. Never logs header values, only whether auth was sent."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            headers = {k.decode().lower(): v.decode() for k, v in scope.get("headers", [])}
            logger.info(
                "inbound %s %s ua=%r source=%s auth_header=%s",
                scope["method"],
                scope["path"],
                headers.get("user-agent", ""),
                headers.get("cf-connecting-ip") or (scope.get("client") or ("?",))[0],
                "authorization" in headers,
            )
        await self.app(scope, receive, send)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    settings = SpikeSettings()
    app = build_server(settings.require_mcp_token()).http_app(path="/mcp")
    uvicorn.run(RequestLogMiddleware(app), host="127.0.0.1", port=settings.spike_mcp_port)


if __name__ == "__main__":
    main()
