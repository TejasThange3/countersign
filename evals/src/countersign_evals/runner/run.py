"""Run scenarios: reset the DB, drive the scenario, read the DB back, score."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import UTC, date, datetime
from decimal import Decimal
from importlib import metadata
from typing import Literal

from pydantic import BaseModel, Field

from countersign_evals.metrics import Summary, summarize
from countersign_evals.metrics.db_diff import evaluate
from countersign_evals.records import (
    ArmorIQMode,
    AssertionResult,
    DriverName,
    ScenarioRun,
)
from countersign_evals.runner.db import DbProbe, DbReset
from countersign_evals.runner.drivers import Driver
from countersign_evals.scenario import MONEY_HOLD_ABOVE, RowAssertion, Scenario

ObservedMode = Literal["live", "disabled", "mixed", "none"]


class RunReport(BaseModel):
    started_at: datetime
    finished_at: datetime
    driver: DriverName
    # What the ToolResults said, never what we asked for. "none" = no step reached a gateway.
    armoriq_mode: ObservedMode
    requested_mode: ArmorIQMode
    armoriq_sdk_version: str | None
    approval_mode: Literal["automated", "supervised"]
    # True when the gateway factory is a test fake: such a report is never a result.
    fake_gateway: bool
    driver_info: dict[str, object]
    money_hold_above: str
    repeats: int
    plan_ids: list[str]
    scenarios: list[ScenarioRun]
    summary: Summary
    mode_mismatch: bool = Field(
        description="requested and observed armoriq_mode differ; the run should not be used"
    )


def sdk_version() -> str | None:
    try:
        return metadata.version("armoriq-sdk")
    except metadata.PackageNotFoundError:
        return None


async def _check_all(probe: DbProbe, assertions: Sequence[RowAssertion]) -> list[AssertionResult]:
    results = []
    for a in assertions:
        rows = await probe.rows(a.table, a.where)
        results.append(evaluate(a, rows))
    return results


def observed_mode(runs: Sequence[ScenarioRun]) -> ObservedMode:
    modes = {s.armoriq_mode for r in runs for s in r.steps if s.armoriq_mode}
    if not modes:
        return "none"
    if len(modes) > 1:
        return "mixed"
    return next(iter(modes))  # type: ignore[return-value]  # one of "live" / "disabled"


async def run_scenario(
    scenario: Scenario,
    driver: Driver,
    reset: DbReset,
    probe: DbProbe,
    mode: ArmorIQMode,
    today: date,
    repeat: int = 0,
) -> ScenarioRun:
    resolved = scenario.resolve_dates(today)
    await reset.reset()
    driver_error: str | None = None
    steps = []
    try:
        steps = await driver.run(resolved, mode)
    except NotImplementedError:
        raise
    except Exception as exc:  # recorded on the run; it then fails its DB check
        driver_error = f"{type(exc).__name__}: {exc}"
    return ScenarioRun(
        scenario_id=scenario.id,
        kind=scenario.kind,
        repeat=repeat,
        steps=steps,
        expected_db=await _check_all(probe, resolved.expected_db),
        attack_harm=await _check_all(probe, resolved.attack_harm),
        driver_error=driver_error,
        known_gap=scenario.known_gap,
    )


async def run_all(
    scenarios: Sequence[Scenario],
    driver: Driver,
    reset: DbReset,
    probe: DbProbe,
    mode: ArmorIQMode,
    approval_mode: Literal["automated", "supervised"],
    fake_gateway: bool,
    repeats: int = 1,
    today: Callable[[], date] = date.today,
) -> RunReport:
    started = datetime.now(UTC)
    runs: list[ScenarioRun] = []
    for repeat in range(repeats):
        for scenario in scenarios:
            runs.append(await run_scenario(scenario, driver, reset, probe, mode, today(), repeat))
    observed = observed_mode(runs)
    return RunReport(
        started_at=started,
        finished_at=datetime.now(UTC),
        driver=driver.name,
        armoriq_mode=observed,
        requested_mode=mode,
        armoriq_sdk_version=sdk_version(),
        approval_mode=approval_mode,
        fake_gateway=fake_gateway,
        driver_info=driver.describe(),
        money_hold_above=str(Decimal(MONEY_HOLD_ABOVE)),
        repeats=repeats,
        plan_ids=sorted({s.plan_id for r in runs for s in r.steps if s.plan_id}),
        scenarios=runs,
        summary=summarize(runs, k=3),
        mode_mismatch=observed not in (mode, "none"),
    )
