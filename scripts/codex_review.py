"""Feedback loop 3: an independent review of this branch by Codex (ChatGPT), read-only.

Run it from inside an agent's worktree after committing:

    python scripts/codex_review.py --task tasks/mcp-server.md

It reviews `main...HEAD` plus any uncommitted changes against the task card and AGENTS.md,
writes the findings to reviews/<branch>-r<N>.md (raw JSON and Codex log next to it), and exits:
    0  verdict PASS (no MUST FIX items)
    1  verdict FAIL (MUST FIX items listed in the review file)
    2  the review itself could not run (Codex missing, not logged in, ...)

Codex runs with a read-only sandbox: it can read files and run read-only commands, never edit.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCHEMA = ROOT / "scripts" / "codex_review_schema.json"

PROMPT = """You are a strict senior reviewer checking code written by another AI agent.
You did not write this code; do not trust its comments or commit messages, check the behaviour.

Inputs:
- The task card the agent was given: {task}
- The project rules: AGENTS.md (read it fully)
- The changes: run `git diff main...HEAD` and `git diff HEAD` (uncommitted), and
  `git status --short` for untracked files. Open any file you need for context.

Check, in order of importance:
1. Correctness: does the change do what the task card's DONE MEANS says? Edge cases, error paths.
2. Security: secrets in code, missing auth, injection, identity taken from model output instead of
   the bridge, anything that lets a tool call skip ArmorIQ.
3. Rule violations from AGENTS.md (files outside the lane's ownership, new deps not justified,
   mocked ArmorIQ results presented as real, tests deleted or skipped).
4. Tests: is the new behaviour actually tested? Would the tests fail if the code were wrong?
5. Simplicity: dead code, needless abstraction.

You may run `python scripts/check.py --changed` to see lint and test status.
Do not edit any file.

Your final answer is JSON matching the provided schema:
- `must_fix`: bugs, security problems, rule violations, missing tests for required behaviour.
- `nice_to_have`: improvements that should not block merging.
- `verdict`: "FAIL" if `must_fix` is non-empty, otherwise "PASS".
- `line`: the most relevant line number (use 1 if the finding is about a whole file).
- `summary`: two or three sentences.
"""


def git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=ROOT, capture_output=True, text=True, check=False
    ).stdout.strip()


def main() -> int:
    parser = argparse.ArgumentParser(description="Codex review of the current branch")
    parser.add_argument("--task", required=True, help="path to the lane's task card")
    parser.add_argument("--model", help="override the Codex model")
    args = parser.parse_args()

    codex = shutil.which("codex")
    if not codex:
        print("codex CLI not found on PATH (npm i -g @openai/codex, then `codex login`).")
        return 2
    if not (ROOT / args.task).exists():
        print(f"task card not found: {args.task}")
        return 2

    branch = git("rev-parse", "--abbrev-ref", "HEAD") or "unknown"
    reviews = ROOT / "reviews"
    reviews.mkdir(exist_ok=True)
    safe = re.sub(r"[^A-Za-z0-9._-]", "-", branch)
    rounds = len(list(reviews.glob(f"{safe}-r*.md"))) + 1
    out_md = reviews / f"{safe}-r{rounds}.md"
    out_json = reviews / f"{safe}-r{rounds}.json"
    out_log = reviews / f"{safe}-r{rounds}.log"

    cmd = [
        codex,
        "exec",
        "--sandbox",
        "read-only",
        "--ephemeral",
        "--cd",
        str(ROOT),
        "--output-schema",
        str(SCHEMA),
        "--output-last-message",
        str(out_json),
    ]
    if args.model:
        cmd += ["--model", args.model]
    cmd.append(PROMPT.format(task=args.task))

    print(f"codex review: branch {branch}, round {rounds} (this takes a few minutes)...")
    with out_log.open("w", encoding="utf-8") as log:
        result = subprocess.run(
            cmd, cwd=ROOT, stdin=subprocess.DEVNULL, stdout=log, stderr=log, check=False
        )
    if result.returncode != 0 or not out_json.exists():
        print(f"codex review failed to run (exit {result.returncode}); see {rel(out_log)}")
        return 2

    try:
        review = json.loads(out_json.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        print(f"codex review returned invalid JSON; treat as FAIL and read {rel(out_json)}")
        return 1

    # The verdict is derived from the findings, not trusted on its own.
    verdict = "FAIL" if review.get("must_fix") else "PASS"
    out_md.write_text(render(branch, rounds, review, verdict), encoding="utf-8")
    print(
        f"codex review verdict: {verdict}  "
        f"({len(review.get('must_fix', []))} must fix, "
        f"{len(review.get('nice_to_have', []))} nice to have; details: {rel(out_md)})"
    )
    return 0 if verdict == "PASS" else 1


def rel(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def render(branch: str, rounds: int, review: dict, verdict: str) -> str:
    def items(findings: list[dict]) -> str:
        if not findings:
            return "- none\n"
        return "".join(
            f"- `{f['file']}:{f['line']}` - {f['problem']} - fix: {f['fix']}\n" for f in findings
        )

    return (
        f"# Codex review: {branch} (round {rounds})\n\n"
        f"## MUST FIX\n{items(review.get('must_fix', []))}\n"
        f"## NICE TO HAVE\n{items(review.get('nice_to_have', []))}\n"
        f"## Summary\n{review.get('summary', '').strip()}\n\n"
        f"VERDICT: {verdict}\n"
    )


if __name__ == "__main__":
    sys.exit(main())
