"""The gateway contract imports and validates; both Day 2 lanes build against it."""

from countersign_agent.contracts import Decision, Outcome, ToolResult


def test_tool_result_round_trip() -> None:
    result = ToolResult(
        tool="issue_refund",
        decision=Decision.HOLD,
        outcome=Outcome.PENDING,
        content="That needs a manager's approval.",
        armoriq_mode="live",
    )
    assert ToolResult.model_validate(result.model_dump()).decision is Decision.HOLD
