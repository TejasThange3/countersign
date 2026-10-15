"""End-to-end runner tests: all 17 scenarios through FakeGatewayFactory, the real Approver over
a fake HTTP transport, and an in-memory FakeHotelDb. Nothing here is a reported result."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import httpx
import pytest
from countersign_agent.contracts import Decision, Outcome
from countersign_evals.approver import Approver, ApproverSettings, RatePacer
from countersign_evals.metrics import attack_succeeded
from countersign_evals.runner.drivers import ConversationDriver, ScriptedDriver
from countersign_evals.runner.report import to_markdown, write_report
from countersign_evals.runner.run import RunReport, run_all
from countersign_evals.runner.settings import load_factory
from countersign_evals.scenario import load_all
from fakes import TODAY, FakeDelegationApi, FakeGatewayFactory, FakeHotelDb
from pydantic import SecretStr

SETTINGS = ApproverSettings(
    armoriq_api_key=SecretStr("ak_live_fake"), armoriq_admin_email="manager@example.com"
)


async def _no_sleep(_: float) -> None:
    return None


def _setup(
    disabled: bool = False, with_approver: bool = True
) -> tuple[FakeHotelDb, FakeDelegationApi, FakeGatewayFactory, ScriptedDriver]:
    db = FakeHotelDb()
    api = FakeDelegationApi()
    factory = FakeGatewayFactory(db, api, disabled=disabled)
    approver = None
    if with_approver:
        http = httpx.AsyncClient(transport=httpx.MockTransport(api))
        approver = Approver(http, SETTINGS, RatePacer(60, sleep=_no_sleep))
    driver = ScriptedDriver(factory, approver, "tests.fakes:FakeGatewayFactory")
    return db, api, factory, driver


async def _run(
    disabled: bool = False, ids: set[str] | None = None, repeats: int = 1
) -> tuple[RunReport, FakeHotelDb, FakeGatewayFactory]:
    db, _, factory, driver = _setup(disabled)
    scenarios = [s for s in load_all() if ids is None or s.id in ids]
    report = await run_all(
        scenarios,
        driver,
        db,
        db,
        "disabled" if disabled else "live",
        approval_mode="automated",
        fake_gateway=True,
        repeats=repeats,
        today=lambda: TODAY,
    )
    return report, db, factory


def _run_of(report: RunReport, sid: str):  # type: ignore[no-untyped-def]
    return next(r for r in report.scenarios if r.scenario_id == sid)


async def test_live_mode_scores_every_scenario_as_designed() -> None:
    report, db, factory = await _run()
    s = report.summary

    assert report.armoriq_mode == "live" and not report.mode_mismatch
    assert report.driver == "scripted" and report.fake_gateway
    assert db.resets == 17  # a fresh seed before every scenario
    assert all(g.closed for g in factory.gateways)
    assert s.task_success.model_dump() == {"hits": 10, "total": 10}
    assert s.decision_accuracy.rate == 1.0
    assert s.stopper_accuracy.rate == 1.0
    assert s.false_positives == []
    # Only A6 (splitting, no velocity rule) gets through, as its known_gap says.
    assert s.attack_success.model_dump() == {"hits": 1, "total": 7}
    assert s.if_supported_accuracy.model_dump() == {"hits": 0, "total": 3}
    # A1's identity pivot and A7's lockout are the bridge's, never ArmorIQ's.
    assert s.stopped_by == {"armoriq": 6, "bridge": 2}  # A1, A2, A3, A4, A5 x2
    assert s.armoriq_overhead.n > 0 and s.armoriq_overhead.p50_ms == 12.0
    assert s.approval_wait.n == 5  # holds: L05, A1, A3, A5 x2
    assert report.plan_ids and all(p.startswith("fake-plan-") for p in report.plan_ids)


async def test_hold_approved_runs_and_hold_rejected_does_not() -> None:
    report, _, _ = await _run(ids={"L05", "A1"})
    l05_refund = _run_of(report, "L05").steps[1]
    assert l05_refund.decision is Decision.HOLD and l05_refund.outcome is Outcome.RAN
    assert l05_refund.approver_action == "approve" and l05_refund.approver_ok
    assert l05_refund.delegation_id and l05_refund.stopped_by is None
    a1_refund = _run_of(report, "A1").steps[1]
    assert a1_refund.decision is Decision.HOLD and a1_refund.outcome is Outcome.NOT_RUN
    assert a1_refund.approver_action == "reject" and a1_refund.stopped_by == "armoriq"


async def test_baseline_mode_lets_attacks_through_except_bridge_rules() -> None:
    report, _, _ = await _run(disabled=True)
    s = report.summary

    assert report.armoriq_mode == "disabled" and not report.mode_mismatch
    assert s.task_success.rate == 1.0
    assert s.decision_accuracy.rate == 1.0  # expectations re-derived for baseline
    attacked = {
        r.scenario_id for r in report.scenarios if r.kind == "adversarial" and attack_succeeded(r)
    }
    # A7 is stopped by the bridge lockout in both modes; everything else gets through.
    assert attacked == {"A1", "A2", "A3", "A4", "A5", "A6"}
    assert s.stopped_by == {"bridge": 2}
    assert s.armoriq_overhead.n == 0 and s.approval_wait.n == 0
    assert report.plan_ids == []


async def test_requested_and_observed_mode_mismatch_is_flagged() -> None:
    db, _, _, driver = _setup(disabled=True)
    report = await run_all(
        [s for s in load_all() if s.id == "L01"],
        driver,
        db,
        db,
        "live",
        approval_mode="automated",
        fake_gateway=True,
        today=lambda: TODAY,
    )
    assert report.mode_mismatch and report.armoriq_mode == "disabled"
    assert "MODE MISMATCH" in to_markdown(report)


async def test_supervised_mode_waits_without_deciding() -> None:
    db, api, _, driver = _setup(with_approver=False)
    assert driver.approval_mode == "supervised"
    report = await run_all(
        [s for s in load_all() if s.id == "L05"],
        driver,
        db,
        db,
        "live",
        approval_mode="supervised",
        fake_gateway=True,
        today=lambda: TODAY,
    )
    step = report.scenarios[0].steps[1]
    assert api.requests == []  # nobody approved, so the fake gateway times out as a refusal
    assert step.approver_action is None and step.outcome is Outcome.NOT_RUN
    assert step.approval_wait_ms is not None


async def test_approver_failure_leaves_the_step_pending_and_never_fakes_an_outcome() -> None:
    db, api, _, driver = _setup()
    api.fail_with = 429
    report = await run_all(
        [s for s in load_all() if s.id == "L05"],
        driver,
        db,
        db,
        "live",
        approval_mode="automated",
        fake_gateway=True,
        today=lambda: TODAY,
    )
    run = report.scenarios[0]
    step = run.steps[1]
    assert step.outcome is Outcome.PENDING and step.approver_ok is False
    assert step.error and "429" in step.error
    assert not run.db_ok  # the refund row was never written
    assert step.stopped_by == "harness_error"  # never credited to ArmorIQ
    assert report.summary.decision_accuracy.model_dump() == {"hits": 1, "total": 2}


async def test_gateway_exception_is_recorded_and_stops_the_scenario() -> None:
    db, _, factory, driver = _setup()
    factory.raise_on.add("issue_refund")
    report = await run_all(
        [s for s in load_all() if s.id == "A5"],
        driver,
        db,
        db,
        "live",
        approval_mode="automated",
        fake_gateway=True,
        today=lambda: TODAY,
    )
    run = report.scenarios[0]
    steps = run.steps
    assert len(steps) == 3  # every scripted step is recorded, reached or not
    assert steps[1].decision is None and "fake gateway failure" in (steps[1].error or "")
    assert steps[2].decision is None and "not reached" in (steps[2].error or "")
    assert factory.gateways[0].closed
    # A crash is never a defence: the attack run is inconclusive, and both missed steps count.
    s = report.summary
    assert s.attack_success.total == 0 and s.inconclusive_attacks == ["A5#0"]
    assert s.decision_accuracy.model_dump() == {"hits": 1, "total": 3}
    assert s.steps_not_clean == 2
    assert "INCONCLUSIVE" in to_markdown(report)


async def test_repeats_feed_pass_k() -> None:
    report, _, _ = await _run(ids={"L01", "L04", "A2"}, repeats=3)
    assert len(report.scenarios) == 9
    assert report.summary.pass_k == {"pass^3": 1.0}


async def test_conversation_driver_is_not_wired_yet() -> None:
    db = FakeHotelDb()
    with pytest.raises(NotImplementedError, match="voice lane"):
        await run_all(
            load_all()[:1],
            ConversationDriver("http://localhost:7860/text"),
            db,
            db,
            "live",
            approval_mode="automated",
            fake_gateway=False,
            today=lambda: TODAY,
        )


async def test_report_files(tmp_path: Path) -> None:
    report, _, _ = await _run(ids={"L05", "A2", "A6"})
    json_path, md_path = write_report(report, tmp_path)

    assert json_path.name.endswith("-live-FAKE.json")
    data = json.loads(json_path.read_text(encoding="utf-8"))
    for key in ("armoriq_mode", "armoriq_sdk_version", "approval_mode", "plan_ids", "driver"):
        assert key in data
    assert data["armoriq_mode"] == "live" and data["driver"] == "scripted"
    assert data["armoriq_sdk_version"]  # read from installed package metadata
    assert data["money_hold_above"] == "100"
    assert data["scenarios"][0]["db_ok"] is True

    md = md_path.read_text(encoding="utf-8")
    assert "FAKE GATEWAY: not a result" in md
    assert "policy decisions only" in md
    assert "| A6 | 0 | attack SUCCEEDED |" in md
    assert "| A2 | 0 | attack stopped |" in md
    assert "not measured" in md


@pytest.mark.parametrize(
    ("path", "error"),
    [("no_colon", ValueError), ("json:dumps", TypeError)],
)
def test_load_factory_rejects_bad_paths(path: str, error: type[Exception]) -> None:
    with pytest.raises(error):
        load_factory(path)


def test_load_factory_accepts_an_instance_or_a_zero_arg_callable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import fakes

    instance = FakeGatewayFactory(FakeHotelDb(), FakeDelegationApi())
    builder: Callable[[], FakeGatewayFactory] = lambda: instance  # noqa: E731 - tiny test factory
    monkeypatch.setattr(fakes, "FACTORY", instance, raising=False)
    monkeypatch.setattr(fakes, "build", builder, raising=False)
    assert load_factory("fakes:FACTORY") is instance
    assert load_factory("fakes:build") is instance
