"""What each smoke case must show for the run to count as proof. smoke.py saves the evidence
first, then exits nonzero on any mismatch, so a wrong policy can't pass silently (on the first
live run a policy row left on its preselected Hold made BLOCK hold instead)."""

from __future__ import annotations

from typing import Literal

from armoriq_spike.sequence import CallRecord

Expected = Literal["ALLOW", "HOLD", "BLOCK", "APPROVED"]

# expected label -> (first decision, approval, outcome)
EXPECTATIONS: dict[Expected, tuple[str, str | None, str]] = {
    "ALLOW": ("allow", None, "ran"),
    "HOLD": ("hold", "approved", "ran"),  # held, approved by a human, then executed
    "BLOCK": ("block", None, "blocked"),  # blocked and never executed
    "APPROVED": ("hold", "approved", "ran"),  # held, approved over HTTP, then executed
}


def mismatches(cases: list[tuple[Expected, CallRecord]]) -> list[str]:
    problems: list[str] = []
    for expected, record in cases:
        decision, approval, outcome = EXPECTATIONS[expected]
        got = (record.decision, record.approval, record.outcome)
        if got != (decision, approval, outcome):
            problems.append(
                f"{expected} {record.tool}: expected decision={decision} approval={approval}"
                f" outcome={outcome}, got decision={got[0]} approval={got[1]} outcome={got[2]}"
                f" (reason={record.reason!r})"
            )
    return problems
