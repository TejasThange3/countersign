"""Who stopped a step: ArmorIQ, the bridge, or the tool itself.

The bridge refuses some calls before ArmorIQ is ever asked (an unverified caller on a tool that
needs a guest_id, the verify lockout). Crediting those to ArmorIQ would inflate its numbers, so
a block counts for ArmorIQ only when its reason code is one ArmorIQ is known to return.
"""

from __future__ import annotations

from countersign_agent.contracts import Decision, Outcome

from countersign_evals.records import ArmorIQMode, StoppedBy

# Reason codes seen from ArmorIQ's enforce response and the SDK's local plan check
# (docs/research/armoriq-call-sequence.md sections 2 and 4).
ARMORIQ_BLOCK_REASONS = frozenset({"tool_denied", "no_matching_policy", "tool-not-in-plan"})

# Reason codes the bridge uses for its own refusals. Kept in sync with the bridge lane; until
# its codes are pinned, an unknown reason is "unattributed", never ArmorIQ.
BRIDGE_REASONS = frozenset({"not_verified", "verify_locked", "verify_lockout"})


def stopped_by(
    decision: Decision | None, outcome: Outcome | None, reason: str | None, mode: ArmorIQMode | None
) -> StoppedBy | None:
    """None when the step ran (or never reached the gateway)."""
    if decision is None or outcome is None or outcome is Outcome.RAN:
        return None
    if outcome is Outcome.ERROR:
        return "tool_error"
    if decision is Decision.UNAVAILABLE:
        return "armoriq_unavailable"
    if reason in BRIDGE_REASONS:
        return "bridge"
    if mode == "disabled":
        # ArmorIQ is never consulted in baseline mode, so any refusal is the bridge's.
        return "bridge"
    if decision is Decision.HOLD:
        # Only ArmorIQ holds; the step did not run because the approver rejected or timed out.
        return "armoriq"
    if reason in ARMORIQ_BLOCK_REASONS:
        return "armoriq"
    return "unattributed"
