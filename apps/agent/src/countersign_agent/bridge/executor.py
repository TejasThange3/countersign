"""The only code that talks to hotel-mcp. The gateway calls it after ArmorIQ allowed a tool
(or in baseline mode), never before: product rule 1."""

from __future__ import annotations

from typing import Any, Protocol

from fastmcp import Client
from pydantic import BaseModel

from countersign_agent.bridge.tools import ToolInfo


class ToolOutput(BaseModel):
    data: Any  # structured content when the tool returns it, else the text
    is_error: bool = False


class ToolExecutor(Protocol):
    async def list_tools(self) -> list[ToolInfo]: ...

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> ToolOutput: ...

    async def close(self) -> None: ...


class McpExecutor:
    """A fastmcp client over streamable HTTP with the bearer token. One per phone call."""

    def __init__(self, client: Client[Any]) -> None:
        self._client = client

    @classmethod
    async def connect(cls, url: str, bearer_token: str) -> McpExecutor:
        client: Client[Any] = Client(url, auth=bearer_token)
        await client.__aenter__()
        return cls(client)

    async def list_tools(self) -> list[ToolInfo]:
        infos = []
        for tool in await self._client.list_tools():
            fastmcp_meta = (tool.meta or {}).get("fastmcp") or {}
            infos.append(
                ToolInfo(
                    name=tool.name,
                    description=tool.description or "",
                    input_schema=tool.input_schema,
                    tags=list(fastmcp_meta.get("tags") or []),
                )
            )
        return infos

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> ToolOutput:
        result = await self._client.call_tool(name, arguments, raise_on_error=False)
        if result.structured_content is not None and not result.is_error:
            data: Any = result.structured_content
            # FastMCP wraps non-object returns (str, list) as {"result": ...}.
            if set(data) == {"result"}:
                data = data["result"]
        else:
            data = "\n".join(getattr(block, "text", "") for block in result.content)
        return ToolOutput(data=data, is_error=result.is_error)

    async def close(self) -> None:
        await self._client.__aexit__(None, None, None)
