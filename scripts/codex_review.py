"""Feedback loop 3: an independent review of this branch by Codex (ChatGPT), read-only.

Run it from inside an agent's worktree after committing:

    python scripts/codex_review.py --task tasks/mcp-server.md

It reviews `main...HEAD` plus any uncommitted changes against the task card and AGENTS.md,
writes the findings to reviews/<branch>-r<N>.md, and exits:
    0  verdict PASS (no MUST FIX items)
    1  verdict FAIL (MUST FIX items listed in the review file)
    2  the review itself could not run (Codex missing, not logged in, ...)

Codex runs with a read-only sandbox: it can read files and run read-only commands, never edit.
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

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

Output format (Markdown, nothing before the first heading):
# Review: <branch>
## MUST FIX
- `file:line` - problem - suggested fix
(write "- none" if there are none)
## NICE TO HAVE
- `file:line` - problem - suggested fix
## Summary
Two or three sentences.

The very last line must be exactly `VERDICT: PASS` (no MUST FIX items) or `VERDICT: FAIL`.
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
    out_file = reviews / f"{safe}-r{rounds}.md"

    cmd = [
        codex,
        "exec",
        "--sandbox",
        "read-only",
        "--ephemeral",
        "--cd",
        str(ROOT),
        "--output-last-message",
        str(out_file),
    ]
    if args.model:
        cmd += ["--model", args.model]
    cmd.append(PROMPT.format(task=args.task))

    print(f"codex review: branch {branch}, round {rounds} -> {out_file.relative_to(ROOT)}")
    result = subprocess.run(cmd, cwd=ROOT, stdin=subprocess.DEVNULL, check=False)
    if result.returncode != 0 or not out_file.exists():
        print(f"codex review failed to run (exit {result.returncode}).")
        return 2

    text = out_file.read_text(encoding="utf-8")
    verdict = re.findall(r"VERDICT:\s*(PASS|FAIL)", text)
    if not verdict:
        print("codex review finished but gave no verdict line; treat as FAIL and read the file.")
        return 1
    print(f"codex review verdict: {verdict[-1]}  (details: {out_file.relative_to(ROOT)})")
    return 0 if verdict[-1] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
