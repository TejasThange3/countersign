"""Write a run report as `<timestamp>.json` plus a Markdown summary next to it."""

from __future__ import annotations

from pathlib import Path

from countersign_evals.metrics import (
    Distribution,
    Ratio,
    attack_inconclusive,
    attack_succeeded,
)
from countersign_evals.records import ScenarioRun
from countersign_evals.runner.run import RunReport
from countersign_evals.scenario import Kind

REPORTS_DIR = Path(__file__).resolve().parents[3] / "reports"


def _pct(r: Ratio) -> str:
    return "n/a" if r.rate is None else f"{r.rate:.0%} ({r.hits}/{r.total})"


def _ms(d: Distribution) -> str:
    if not d.n:
        return "n/a"
    return f"p50 {d.p50_ms:.0f} ms, p95 {d.p95_ms:.0f} ms (n={d.n})"


def _decisions(run: ScenarioRun) -> str:
    parts = []
    for s in run.steps:
        got = s.decision.value if s.decision else "-"
        mark = "" if got == s.expected else " ✗"
        who = f" by {s.stopped_by}" if s.stopped_by else ""
        parts.append(f"{s.tool}: {got}{who}{mark}")
    return "<br>".join(parts)


def _result(run: ScenarioRun) -> str:
    if run.driver_error:
        return f"ERROR: {run.driver_error}"
    if run.kind is Kind.ADVERSARIAL:
        if attack_succeeded(run):
            return "attack SUCCEEDED"
        return "INCONCLUSIVE (error or outage)" if attack_inconclusive(run) else "attack stopped"
    if run.errored:
        return "FAIL (step error)"
    return "pass" if run.task_ok else "FAIL"


def to_markdown(report: RunReport) -> str:
    s = report.summary
    lines = [f"# Eval run {report.started_at:%Y-%m-%d %H:%M:%S} UTC", ""]
    if report.fake_gateway:
        lines += ["> **FAKE GATEWAY: not a result.** Test wiring only (AGENTS.md rule 5).", ""]
    if report.mode_mismatch:
        lines += [
            f"> **MODE MISMATCH:** requested `{report.requested_mode}`, gateway reported "
            f"`{report.armoriq_mode}`. Do not use this run.",
            "",
        ]
    if report.driver == "scripted":
        lines += [
            "> Scripted driver: tool calls are replayed, so this tests policy decisions only, "
            "not what the LLM would choose.",
            "",
        ]
    lines += [
        "| Field | Value |",
        "|---|---|",
        f"| armoriq_mode | `{report.armoriq_mode}` |",
        f"| driver | `{report.driver}` |",
        f"| approval mode | `{report.approval_mode}` |",
        f"| armoriq-sdk | `{report.armoriq_sdk_version}` |",
        f"| models | `{report.driver_info.get('models')}` |",
        f"| money hold above | ${report.money_hold_above} |",
        f"| repeats | {report.repeats} |",
        f"| plan ids | {len(report.plan_ids)} |",
        "",
        "## Summary",
        "",
        "| Metric | Value |",
        "|---|---|",
        f"| Task success (legit, DB diff) | {_pct(s.task_success)} |",
        f"| Decision accuracy | {_pct(s.decision_accuracy)} |",
        f"| Refused by the expected party | {_pct(s.stopper_accuracy)} |",
        f"| If-supported features (A6/A7) | {_pct(s.if_supported_accuracy)} |",
        f"| Attack success rate | {_pct(s.attack_success)} |",
        f"| Inconclusive attack runs | {', '.join(s.inconclusive_attacks) or 'none'} |",
        f"| Steps with errors or not reached | {s.steps_not_clean} |",
        f"| Legit actions wrongly refused | {len(s.false_positives)} |",
        f"| Stopped by | {s.stopped_by or '-'} |",
        f"| ArmorIQ overhead per call | {_ms(s.armoriq_overhead)} |",
        f"| Hold wait (gateway.wait; {report.approval_mode}) | {_ms(s.approval_wait)} |",
        *(
            f"| {k} (legit) | {'n/a (run with --repeat 3)' if v is None else f'{v:.0%}'} |"
            for k, v in s.pass_k.items()
        ),
        f"| WER | {s.wer.note} |",
        f"| Latency per stage | {s.latency_per_stage.note} |",
        "",
        "## Scenarios",
        "",
        "| Scenario | Run | Result | Decisions (✗ = unexpected) | Known gap |",
        "|---|---|---|---|---|",
    ]
    for run in report.scenarios:
        gap = (run.known_gap or "").replace("\n", " ")
        lines.append(
            f"| {run.scenario_id} | {run.repeat} | {_result(run)} | {_decisions(run)} | {gap} |"
        )
    return "\n".join(lines) + "\n"


def write_report(report: RunReport, out_dir: Path = REPORTS_DIR) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = report.started_at.strftime("%Y%m%dT%H%M%SZ") + f"-{report.armoriq_mode}"
    if report.fake_gateway:
        stem += "-FAKE"
    json_path = out_dir / f"{stem}.json"
    md_path = out_dir / f"{stem}.md"
    json_path.write_text(report.model_dump_json(indent=2), encoding="utf-8")
    md_path.write_text(to_markdown(report), encoding="utf-8")
    return json_path, md_path
