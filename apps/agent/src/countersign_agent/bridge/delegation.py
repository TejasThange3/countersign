"""Approver side of a hold. The SDK only ever requests and polls delegations; it has no
approve/reject call, so the eval runner's approver needs this raw HTTP call.

Docs (platform/api-reference) place /delegation/* under API-key auth (`x-api-key`, or
`Authorization: Bearer <key>`). What the backend requires was found live on 2026-10-14:
`delegationId` + `approverEmail` in the body and an `X-User-Email` header. Without a declared
approver limit the call is refused with "exceeds your approval limit of 0", even for an
org_admin whose /delegation/my-role limit is 1e9, so the role and limit are read from
my-role and sent as `approverRole` / `approverLimit`, mirroring how the SDK sends
`requesterRole` / `requesterLimit` on /delegation/request.
"""

from __future__ import annotations

from typing import Any, Literal

import httpx
from pydantic import BaseModel

Decision = Literal["approve", "reject"]


class ApproverRole(BaseModel):
    role: str
    limit: float


class DelegationDecisionResult(BaseModel):
    decision: Decision
    status_code: int
    ok: bool
    body: Any


def _body(resp: httpx.Response) -> Any:
    try:
        return resp.json()
    except ValueError:
        return resp.text[:500]


async def fetch_approver_role(
    http: httpx.AsyncClient, backend_endpoint: str, headers: dict[str, str], email: str
) -> ApproverRole:
    """GET /delegation/my-role, the same lookup the SDK's _resolve_user_role makes."""
    resp = await http.get(
        f"{backend_endpoint}/delegation/my-role",
        headers={**headers, "X-User-Email": email},
        timeout=10.0,
    )
    resp.raise_for_status()
    data = resp.json()
    return ApproverRole(role=data["role"], limit=float(data.get("limit") or 0))


async def decide_delegation(
    http: httpx.AsyncClient,
    backend_endpoint: str,
    delegation_id: str,
    headers: dict[str, str],
    approver_email: str,
    decision: Decision = "approve",
    approver: ApproverRole | None = None,
) -> DelegationDecisionResult:
    body: dict[str, Any] = {"delegationId": delegation_id, "approverEmail": approver_email}
    # Only approve takes them; reject 400s with "property approverRole should not exist".
    if approver is not None and decision == "approve":
        body |= {"approverRole": approver.role, "approverLimit": approver.limit}
    resp = await http.post(
        f"{backend_endpoint}/delegation/{decision}",
        json=body,
        headers={**headers, "X-User-Email": approver_email},
        timeout=15.0,
    )
    return DelegationDecisionResult(
        decision=decision, status_code=resp.status_code, ok=resp.is_success, body=_body(resp)
    )
