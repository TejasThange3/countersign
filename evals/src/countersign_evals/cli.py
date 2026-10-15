"""`countersign-evals` command line.

countersign-evals list
countersign-evals run [--scenario L05 A3] [--repeat 3] [--baseline] [--supervised]
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from collections.abc import Sequence
from pathlib import Path

import httpx
from sqlalchemy.engine import make_url

from countersign_evals.approver import Approver, load_approver_settings
from countersign_evals.records import ArmorIQMode
from countersign_evals.runner.db import CommandReset, PostgresProbe
from countersign_evals.runner.drivers import ConversationDriver, Driver, ScriptedDriver
from countersign_evals.runner.report import REPORTS_DIR, write_report
from countersign_evals.runner.run import run_all
from countersign_evals.runner.settings import (
    REPO_ROOT,
    RunnerSettings,
    is_fake_factory,
    load_factory,
)
from countersign_evals.scenario import load_all

LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="countersign-evals", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list", help="list the scenarios")
    run = sub.add_parser("run", help="run scenarios and write a report")
    run.add_argument("--scenario", nargs="*", default=None, help="scenario ids (default: all)")
    run.add_argument("--repeat", type=int, default=1, help="runs per scenario (3 for pass^3)")
    run.add_argument(
        "--baseline", action="store_true", help="DISABLE_ARMORIQ=1: the same agent, no ArmorIQ"
    )
    run.add_argument(
        "--supervised",
        action="store_true",
        help="no automated approver: a person decides holds in the ArmorIQ console",
    )
    run.add_argument("--driver", choices=["scripted", "conversation"], default="scripted")
    run.add_argument("--out", type=Path, default=REPORTS_DIR)
    run.add_argument(
        "--allow-remote-db",
        action="store_true",
        help="allow DATABASE_URL to point somewhere other than localhost (it gets wiped)",
    )
    return parser


async def _run(args: argparse.Namespace) -> int:
    if args.baseline:
        # Set before the factory is imported, so the bridge reads it from its own settings.
        os.environ["DISABLE_ARMORIQ"] = "1"
    settings = RunnerSettings()
    mode: ArmorIQMode = "disabled" if settings.disable_armoriq else "live"
    scenarios = load_all()
    if args.scenario:
        wanted = set(args.scenario)
        scenarios = [s for s in scenarios if s.id in wanted]
        missing = wanted - {s.id for s in scenarios}
        if missing:
            print(f"Unknown scenario ids: {sorted(missing)}", file=sys.stderr)
            return 2

    host = make_url(settings.database_url).host
    if host not in LOCAL_HOSTS and not args.allow_remote_db:
        print(
            f"Refusing to reset a non-local database ({host}): every scenario wipes it. "
            "Pass --allow-remote-db if that is really what you want.",
            file=sys.stderr,
        )
        return 2

    probe = PostgresProbe.from_url(settings.database_url)
    async with httpx.AsyncClient() as http:
        approver = None
        if mode == "live" and not args.supervised:
            approver = Approver(http, load_approver_settings())
        driver: Driver
        if args.driver == "conversation":
            driver = ConversationDriver(settings.agent_text_url)
            fake = False
        else:
            factory = load_factory(settings.gateway_factory)
            fake = is_fake_factory(factory)
            driver = ScriptedDriver(
                factory, approver, settings.gateway_factory, settings.approval_wait_timeout_s
            )
        try:
            report = await run_all(
                scenarios,
                driver,
                CommandReset(settings.reset_command(), settings.database_url, REPO_ROOT),
                probe,
                mode,
                approval_mode="automated" if approver else "supervised",
                fake_gateway=fake,
                repeats=args.repeat,
            )
        finally:
            await probe.close()
    json_path, md_path = write_report(report, args.out)
    print(f"Wrote {json_path}\nWrote {md_path}")
    return 1 if report.mode_mismatch else 0


def main(argv: Sequence[str] | None = None) -> None:
    args = _parser().parse_args(argv)
    if args.command == "list":
        for s in load_all():
            print(f"{s.id:4} {s.kind:12} {s.title}")
        return
    sys.exit(asyncio.run(_run(args)))
