"""CLI guard rails and the reset command's environment. No database needed."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from countersign_evals.approver.settings import running_in_ci
from countersign_evals.cli import main
from countersign_evals.runner.db import CommandReset
from countersign_evals.runner.settings import is_fake_factory
from fakes import FakeDelegationApi, FakeGatewayFactory, FakeHotelDb


async def test_reset_subprocess_gets_the_probes_database_url(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://wrong/db")
    check = (
        "import os, sys, pathlib; "
        "ok = os.environ['DATABASE_URL'] == 'postgresql+asyncpg://probe/db' "
        f"and pathlib.Path.cwd() == pathlib.Path({str(tmp_path)!r}); "
        "sys.exit(0 if ok else 3)"
    )
    await CommandReset(
        [sys.executable, "-c", check], "postgresql+asyncpg://probe/db", tmp_path
    ).reset()


async def test_reset_failure_raises_with_output() -> None:
    reset = CommandReset([sys.executable, "-c", "print('nope'); raise SystemExit(4)"])
    with pytest.raises(RuntimeError, match=r"exit 4\).*nope"):
        await reset.reset()


def test_run_refuses_a_remote_database(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@db.example.com:5432/prod")
    with pytest.raises(SystemExit) as exc:
        main(["run", "--scenario", "L01"])
    assert exc.value.code == 2
    assert "non-local database (db.example.com)" in capsys.readouterr().err


def test_list(capsys: pytest.CaptureFixture[str]) -> None:
    main(["list"])
    out = capsys.readouterr().out.splitlines()
    assert len(out) == 17 and out[0].startswith("L01") and out[-1].startswith("A7")


@pytest.mark.parametrize(
    ("value", "expected"),
    [("", False), ("0", False), ("false", False), ("FALSE", False), ("true", True), ("1", True)],
)
def test_running_in_ci(monkeypatch: pytest.MonkeyPatch, value: str, expected: bool) -> None:
    monkeypatch.setenv("CI", value)
    assert running_in_ci() is expected


def test_fake_factories_are_detected() -> None:
    assert is_fake_factory(FakeGatewayFactory(FakeHotelDb(), FakeDelegationApi()))

    class Stub:
        is_fake = True

    class Real:
        pass

    assert is_fake_factory(Stub())
    assert not is_fake_factory(Real())
