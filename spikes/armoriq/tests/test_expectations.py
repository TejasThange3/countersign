from __future__ import annotations

from typing import Any

import pytest
from armoriq_spike.expectations import mismatches
from armoriq_spike.sequence import CallRecord


def rec(**kw: Any) -> CallRecord:
    base: dict[str, Any] = {
        "tool": "t",
        "user_email": "<guest>",
        "decision": "allow",
        "outcome": "ran",
    }
    return CallRecord(**(base | kw))


def test_the_three_good_cases_pass() -> None:
    cases = [
        ("ALLOW", rec()),
        ("HOLD", rec(decision="hold", approval="approved")),
        ("BLOCK", rec(decision="block", outcome="blocked")),
    ]
    assert mismatches(cases) == []


def test_block_that_was_held_and_timed_out_fails() -> None:
    # The real first run: export_guest_list was left on Hold in the policy.
    problems = mismatches(
        [
            (
                "BLOCK",
                rec(
                    tool="export_guest_list", decision="hold", approval="timeout", outcome="timeout"
                ),
            )
        ]
    )
    assert len(problems) == 1
    assert "export_guest_list" in problems[0]


@pytest.mark.parametrize(
    "record",
    [
        rec(decision="block", outcome="blocked"),  # everything blocked
        rec(decision="error", outcome="error"),  # enforcement error
        rec(decision="allow", outcome="error"),  # allowed but the tool failed
    ],
)
def test_allow_mismatches_are_reported(record: CallRecord) -> None:
    assert len(mismatches([("ALLOW", record)])) == 1


def test_hold_must_be_approved_and_run() -> None:
    rejected = rec(decision="hold", approval="rejected", outcome="rejected")
    assert len(mismatches([("HOLD", rejected), ("APPROVED", rejected)])) == 2
