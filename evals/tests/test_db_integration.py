"""The real reset command and Postgres probe against the real seed.

Needs `docker compose -f infra/docker-compose.yml up -d`. Uses its own database
(countersign_evals_test) so a reset never wipes the database other lanes are working against.
Pins the seed facts the scenario files rely on: LRK-100n is booking id n owned by guest n.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from datetime import date

import pytest
from countersign_evals.runner.db import CommandReset, PostgresProbe
from countersign_evals.runner.settings import RunnerSettings
from countersign_evals.scenario import load_all
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine

pytestmark = pytest.mark.integration

TEST_DB = "countersign_evals_test"


@pytest.fixture
async def test_db_url(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[str]:
    base = make_url(RunnerSettings().database_url)
    admin = create_async_engine(base.set(database="postgres"), isolation_level="AUTOCOMMIT")
    async with admin.connect() as conn:
        exists = await conn.scalar(
            text("SELECT 1 FROM pg_database WHERE datname = :n"), {"n": TEST_DB}
        )
        if not exists:
            await conn.execute(text(f'CREATE DATABASE "{TEST_DB}"'))
    await admin.dispose()
    url = base.set(database=TEST_DB).render_as_string(hide_password=False)
    # The reset subprocess inherits this, and env vars beat .env in pydantic-settings.
    monkeypatch.setenv("DATABASE_URL", url)
    settings = RunnerSettings()
    migrate = [*settings.reset_command()[:-2], "migrate"]
    await CommandReset(migrate).reset()
    yield url


async def test_reset_and_probe_match_the_seed_the_scenarios_assume(test_db_url: str) -> None:
    assert os.environ["DATABASE_URL"] == test_db_url
    await CommandReset(RunnerSettings().reset_command()).reset()
    probe = PostgresProbe.from_url(test_db_url)
    try:
        for n, last in [(1, "Okafor"), (2, "Brandt"), (3, "Lindqvist"), (7, "Quillfeather")]:
            (booking,) = await probe.rows("bookings", {"ref": f"LRK-{1000 + n}"})
            assert booking["id"] == n and booking["guest_id"] == n
            (guest,) = await probe.rows("guests", {"id": n})
            assert guest["last_name"] == last
        for n in (1, 2, 3):
            (booking,) = await probe.rows("bookings", {"id": n})
            assert booking["status"] == "confirmed"
            assert (booking["check_in"] - date.today()).days >= 5  # always cancellable free
        assert len(await probe.rows("bookings", {})) == 50
        assert len(await probe.rows("booking_notes", {"booking_id": 1})) == 1
        assert len(await probe.rows("booking_notes", {"booking_id": 2})) == 0

        # Every scenario's expected_db holds or fails cleanly against a fresh seed: no SQL
        # errors from dates, amounts or unknown columns.
        for scenario in load_all():
            for a in scenario.resolve_dates(date.today()).expected_db:
                await probe.rows(a.table, a.where)
        refunds = await probe.rows("payments", {"booking_id": 1, "amount": 60})
        assert refunds == []
    finally:
        await probe.close()
