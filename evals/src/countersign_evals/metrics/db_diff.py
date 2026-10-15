"""Task success without an LLM judge: row-level assertions against the final database state."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from countersign_evals.records import AssertionResult
from countersign_evals.scenario import RowAssertion


def normalize(value: Any) -> Any:
    """One comparable form per value: numbers as Decimal (so 60 == 60.00 == Decimal('60.00')),
    dates as ISO strings (scenarios write dates as strings after resolve_dates)."""
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, int | float | Decimal):
        return Decimal(str(value)).normalize()
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return value


def row_matches(row: Mapping[str, Any], where: Mapping[str, Any]) -> bool:
    return all(normalize(row.get(k)) == normalize(v) for k, v in where.items())


def evaluate(assertion: RowAssertion, rows: Iterable[Mapping[str, Any]]) -> AssertionResult:
    """Check one assertion against the rows its `where` selected."""
    matching = [r for r in rows if row_matches(r, assertion.where)]
    problems: list[str] = []
    if assertion.count is not None and len(matching) != assertion.count:
        problems.append(f"expected {assertion.count} row(s), found {len(matching)}")
    if assertion.values is not None:
        if not matching:
            problems.append("expected at least one matching row, found none")
        for row in matching:
            wrong = {
                k: row.get(k)
                for k, v in assertion.values.items()
                if normalize(row.get(k)) != normalize(v)
            }
            if wrong:
                problems.append(f"row id={row.get('id')} has {wrong}, expected {assertion.values}")
    return AssertionResult(
        assertion=assertion,
        passed=not problems,
        matched_rows=len(matching),
        detail="; ".join(problems),
    )
