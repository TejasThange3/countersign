"""Turn the gateway's `ToolSpec`s into Pipecat function definitions.

Every definition gets the same handler, which hands the call to a `ToolRouter`. The router is
the only thing that talks to the gateway, so no tool can reach hotel-mcp around ArmorIQ.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from pipecat.adapters.schemas.function_schema import FunctionSchema
from pipecat.adapters.schemas.tools_schema import ToolsSchema
from pipecat.services.llm_service import FunctionCallParams

from countersign_agent.contracts import ToolSpec

ToolHandler = Callable[[FunctionCallParams], Awaitable[None]]


def to_function_schema(spec: ToolSpec, handler: ToolHandler) -> FunctionSchema:
    params = spec.parameters
    return FunctionSchema(
        name=spec.name,
        description=spec.description,
        properties=dict(params.get("properties", {})),
        required=list(params.get("required", [])),
        handler=handler,
    )


def build_tools_schema(specs: list[ToolSpec], handler: ToolHandler) -> ToolsSchema:
    return ToolsSchema(standard_tools=[to_function_schema(s, handler) for s in specs])
