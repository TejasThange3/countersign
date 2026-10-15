"""Live smoke run: the real bridge, real ArmorIQ, the real approver, the local Postgres.

Marked `live`, so `scripts/check.py` never runs it. Run on purpose:
    uv run --project evals pytest -m live -s
It writes nothing to evals/reports/ (reports go to a temp dir); the CLI makes real reports.
Skips until the bridge lane is merged (countersign_agent.bridge importable).
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import httpx
import pytest
from countersign_evals.approver import Approver, load_approver_settings
from countersign_evals.runner.db import CommandReset, PostgresProbe
from countersign_evals.runner.drivers import ScriptedDriver
from countersign_evals.runner.report import write_report
from countersign_evals.runner.run import run_all
from countersign_evals.runner.settings import (
    REPO_ROOT,
    RunnerSettings,
    is_fake_factory,
    load_factory,
)
from countersign_evals.scenario import load_all

pytestmark = pytest.mark.live


@pytest.mark.skipif(
    importlib.util.find_spec("countersign_agent.bridge") is None,
    reason="bridge lane not merged yet",
)
async def test_live_allow_hold_block(tmp_path: Path) -> None:
    settings = RunnerSettings()
    factory = load_factory(settings.gateway_factory)
    assert not is_fake_factory(factory)
    probe = PostgresProbe.from_url(settings.database_url)
    async with httpx.AsyncClient() as http:
        driver = ScriptedDriver(
            factory, Approver(http, load_approver_settings()), settings.gateway_factory
        )
        try:
            report = await run_all(
                [s for s in load_all() if s.id in {"L04", "L05", "A2"}],
                driver,
                CommandReset(settings.reset_command(), settings.database_url, REPO_ROOT),
                probe,
                "live",
                approval_mode="automated",
                fake_gateway=False,
            )
        finally:
            await probe.close()
    json_path, _ = write_report(report, tmp_path)
    print(f"live smoke report: {json_path}")
    assert report.armoriq_mode == "live" and not report.mode_mismatch
    assert report.plan_ids
    assert report.summary.decision_accuracy.rate == 1.0
