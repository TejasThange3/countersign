"""Automated approver for held calls: decides each hold the way the scenario file says."""

from __future__ import annotations

import httpx

from countersign_evals.approver.delegation import (
    Action,
    ApproverRole,
    DelegationDecisionResult,
    decide_delegation,
    fetch_approver_role,
)
from countersign_evals.approver.pacing import RatePacer
from countersign_evals.approver.settings import (
    ApproverConfigError,
    ApproverSettings,
    load_approver_settings,
)

__all__ = [
    "Action",
    "Approver",
    "ApproverConfigError",
    "ApproverRole",
    "ApproverSettings",
    "DelegationDecisionResult",
    "RatePacer",
    "load_approver_settings",
]


class Approver:
    """Approves or rejects delegations as the configured manager, paced under the rate limit.

    The role and limit are read once from /delegation/my-role and reused for the run.
    """

    def __init__(
        self, http: httpx.AsyncClient, settings: ApproverSettings, pacer: RatePacer | None = None
    ) -> None:
        self._http = http
        self._settings = settings
        self._pacer = pacer or RatePacer(settings.approver_calls_per_minute)
        self._role: ApproverRole | None = None

    @property
    def _headers(self) -> dict[str, str]:
        return {"X-API-Key": self._settings.armoriq_api_key.get_secret_value()}

    async def role(self) -> ApproverRole:
        if self._role is None:
            await self._pacer.wait()
            self._role = await fetch_approver_role(
                self._http,
                self._settings.armoriq_backend_endpoint,
                self._headers,
                self._settings.armoriq_admin_email,
            )
        return self._role

    async def decide(self, delegation_id: str, action: Action) -> DelegationDecisionResult:
        role = await self.role() if action == "approve" else None
        await self._pacer.wait()
        return await decide_delegation(
            self._http,
            self._settings.armoriq_backend_endpoint,
            delegation_id,
            self._headers,
            self._settings.armoriq_admin_email,
            action,
            role,
        )
