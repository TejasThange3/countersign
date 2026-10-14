"""Bearer auth on the real HTTP app: a missing or wrong token is rejected before any tool runs.

The server runs in uvicorn on a background thread so the streamable HTTP transport (and its
lifespan) behaves exactly as deployed.
"""

import socket
import threading
import time
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest
import uvicorn
from fastmcp import Client
from hotel_mcp.config import Settings
from hotel_mcp.server import BearerAuthMiddleware, create_app
from mcp.shared.exceptions import MCPError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool
from starlette.types import Message, Receive, Scope, Send

from tests.conftest import TODAY

TOKEN = "test-token-not-a-secret"  # noqa: S105 - fake token for a local test server


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@pytest.fixture
def base_url(sessionmaker, tmp_path: Path) -> Iterator[str]:  # type: ignore[no-untyped-def]
    # Depends on `sessionmaker` so the SQLite file is created and seeded first. The server gets
    # its own engine because it runs on a different event loop (NullPool: no shared connections).
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'hotel.db'}", poolclass=NullPool)
    app = create_app(TOKEN, async_sessionmaker(engine), today=lambda: TODAY)
    port = _free_port()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started:
        if time.monotonic() > deadline:
            raise RuntimeError("test server did not start")
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    thread.join(timeout=10)


MCP_INIT = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2025-06-18",
        "capabilities": {},
        "clientInfo": {"name": "test", "version": "0"},
    },
}
MCP_HEADERS = {"Accept": "application/json, text/event-stream"}


@pytest.mark.parametrize(
    "authorization",
    [
        None,
        "Bearer wrong-token",
        f"bearer {TOKEN}",
        TOKEN,
        f"Bearer {TOKEN}x",
        "Bearer",
    ],
)
async def test_mcp_rejects_missing_or_wrong_token(base_url: str, authorization: str | None) -> None:
    headers = dict(MCP_HEADERS)
    if authorization is not None:
        headers["Authorization"] = authorization
    async with httpx.AsyncClient() as http:
        response = await http.post(f"{base_url}/mcp", json=MCP_INIT, headers=headers)
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


async def test_mcp_client_with_correct_token_can_call_tools(base_url: str) -> None:
    async with Client(f"{base_url}/mcp", auth=TOKEN) as client:
        result = await client.call_tool(
            "verify_guest", {"booking_ref": "LRK-1001", "last_name": "Okafor"}
        )
    assert result.structured_content is not None
    assert result.structured_content["verified"] is True


async def test_mcp_client_with_wrong_token_fails(base_url: str) -> None:
    # The raw 401 is asserted above; this checks the real client surfaces it as a failure.
    with pytest.raises(MCPError):
        async with Client(f"{base_url}/mcp", auth="wrong") as client:
            await client.list_tools()


async def test_health_is_open(base_url: str) -> None:
    async with httpx.AsyncClient() as http:
        response = await http.get(f"{base_url}/health")
    assert response.status_code == 200
    assert response.text == "ok"


def test_empty_token_refuses_to_build_app(sessionmaker) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(ValueError, match="MCP_BEARER_TOKEN"):
        create_app("", sessionmaker)


async def test_non_http_scopes_fail_closed() -> None:
    called = False

    async def app(scope: Scope, receive: Receive, send: Send) -> None:
        nonlocal called
        called = True

    sent: list[Message] = []

    async def send(message: Message) -> None:
        sent.append(message)

    async def receive() -> Message:
        return {"type": "websocket.connect"}

    middleware = BearerAuthMiddleware(app, TOKEN, open_paths=frozenset({"/health"}))
    await middleware({"type": "websocket", "path": "/mcp", "headers": []}, receive, send)
    assert not called
    assert sent == [{"type": "websocket.close", "code": 1008}]


def test_token_whitespace_is_stripped(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MCP_BEARER_TOKEN", f"  {TOKEN}\n")
    assert Settings(_env_file=None).mcp_bearer_token == TOKEN  # type: ignore[call-arg]
