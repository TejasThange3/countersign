"""Demo manager desk: the person on a call decides that call's own held request.

In production a hotel manager approves or rejects held actions in the ArmorIQ console. For the
public demo, judges are not members of our ArmorIQ organisation, so the website hands them that
decision instead. Their click still goes to ArmorIQ's real approval API (as ARMORIQ_ADMIN_EMAIL,
with the role and limit ArmorIQ itself reports for that email, never declared by us), so the
decision is ArmorIQ's record, and the agent's own polling picks it up exactly as it would a
console approval.

The caller never names a delegation: the desk is only ever handed a held result that the
server looked up from the caller's own call.
"""

from __future__ import annotations

import logging
from typing import Protocol

import httpx

from countersign_agent.bridge.delegation import (
    ApproverRole,
    Decision,
    DelegationDecisionResult,
    decide_delegation,
    fetch_approver_role,
)
from countersign_agent.contracts import ToolResult

logger = logging.getLogger(__name__)


class ManagerDesk(Protocol):
    async def decide(self, held: ToolResult, decision: Decision) -> DelegationDecisionResult: ...


class ArmorIQManagerDesk:
    def __init__(self, api_key: str, approver_email: str, backend_endpoint: str) -> None:
        if not api_key or not approver_email:
            raise ValueError("the manager desk needs ARMORIQ_API_KEY and ARMORIQ_ADMIN_EMAIL")
        self._headers = {"X-API-Key": api_key}
        self._email = approver_email
        self._endpoint = backend_endpoint.rstrip("/")
        self._role: ApproverRole | None = None

    async def decide(self, held: ToolResult, decision: Decision) -> DelegationDecisionResult:
        if not held.delegation_id:
            raise ValueError(f"held {held.tool} has no delegation id; nothing to decide")
        async with httpx.AsyncClient() as http:
            if decision == "approve" and self._role is None:
                self._role = await fetch_approver_role(
                    http, self._endpoint, self._headers, self._email
                )
            result = await decide_delegation(
                http,
                self._endpoint,
                held.delegation_id,
                self._headers,
                self._email,
                decision,
                approver=self._role if decision == "approve" else None,
            )
        logger.info("demo manager %s %s: ArmorIQ %s", decision, held.tool, result.status_code)
        return result
