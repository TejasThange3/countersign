"""Builds one GovernedGateway per phone call. Implements contracts.GatewayFactory.

The ArmorIQ client is built once per process, lazily, off the event loop (its constructor
checks the key over blocking HTTP). Each call gets its own MCP connection, tool discovery and
ArmorIQ session.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable

from armoriq_sdk import ArmorIQClient

from countersign_agent.bridge.approval import CheckedApprovals
from countersign_agent.bridge.armoriq_setup import build_client, start_user_session
from countersign_agent.bridge.enforcer import (
    ArmorIQEnforcer,
    DisabledEnforcer,
    Enforcer,
    UnavailableEnforcer,
)
from countersign_agent.bridge.executor import McpExecutor, ToolExecutor
from countersign_agent.bridge.gateway import GovernedGateway
from countersign_agent.bridge.identity import CallIdentity
from countersign_agent.bridge.masking import Masker
from countersign_agent.bridge.settings import BridgeSettings
from countersign_agent.bridge.tools import convert_tools
from countersign_agent.contracts import EventSink

logger = logging.getLogger("countersign_agent.bridge.gateway_factory")

ExecutorFactory = Callable[[], Awaitable[ToolExecutor]]
EnforcerFactory = Callable[[list[str]], Awaitable[Enforcer]]


class GovernedGatewayFactory:
    def __init__(
        self,
        settings: BridgeSettings | None = None,
        *,
        executor_factory: ExecutorFactory | None = None,
        enforcer_factory: EnforcerFactory | None = None,
    ) -> None:
        self.settings = settings or BridgeSettings()
        self.masker = Masker(self.settings.identity_mask() | self.settings.secret_mask())
        self._executor_factory = executor_factory or self._connect_mcp
        if enforcer_factory is not None:
            self._enforcer_factory = enforcer_factory
        elif self.settings.disable_armoriq:
            self._enforcer_factory = self._disabled_enforcer
        else:
            self._enforcer_factory = self._armoriq_enforcer
        self._client: ArmorIQClient | None = None
        self._client_lock = asyncio.Lock()

    async def open_call(self, call_id: str, events: EventSink | None = None) -> GovernedGateway:
        executor = await self._executor_factory()
        try:
            tools = convert_tools(await executor.list_tools())
            enforcer = await self._enforcer_factory(list(tools))
        except BaseException:
            await executor.close()
            raise
        gateway = GovernedGateway(
            call_id,
            tools=tools,
            enforcer=enforcer,
            executor=executor,
            identity=CallIdentity(self.settings.armoriq_verify_max_attempts),
            identities={
                "unverified": self.settings.armoriq_user_unverified,
                "guest": self.settings.armoriq_user_guest,
            },
            masker=self.masker,
            events=events,
        )
        try:
            await gateway.start()
        except BaseException:
            # Includes cancellation (the caller hung up during the first plan).
            await gateway.close()
            raise
        return gateway

    async def _connect_mcp(self) -> ToolExecutor:
        return await McpExecutor.connect(self.settings.mcp_url, self.settings.require_mcp_token())

    async def _disabled_enforcer(self, tool_names: list[str]) -> Enforcer:
        return DisabledEnforcer()

    async def _armoriq_enforcer(self, tool_names: list[str]) -> Enforcer:
        try:
            client = await self._armoriq_client()
        except Exception:
            # Not cached: the next call tries again.
            logger.exception("ArmorIQ client unavailable; this call fails closed")
            return UnavailableEnforcer()
        settings = self.settings
        return ArmorIQEnforcer(
            session_factory=lambda email: start_user_session(client, settings, email),
            approvals=CheckedApprovals(client),
            tool_names=tool_names,
            poll_seconds=settings.armoriq_approval_poll_seconds,
        )

    async def _armoriq_client(self) -> ArmorIQClient:
        async with self._client_lock:
            if self._client is None:
                self._client = await asyncio.to_thread(build_client, self.settings)
            return self._client
