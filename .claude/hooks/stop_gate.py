"""Feedback loop 2 (Stop hook): Claude may not finish while the checks are red.

When the agent tries to end its turn, this runs `scripts/check.py --changed` in the agent's own
checkout (the worktree, taken from the hook's `cwd`). If anything fails, it blocks the stop and
hands the failure output back to Claude as the reason to keep going.

Safety valves, so it can never trap an agent:
- Only projects with changes vs main are checked; a turn with no code changes passes instantly.
- After MAX_BLOCKS consecutive blocked stops in one session it lets the agent stop and tells the
  user (the agent is then expected to report what is still failing).
- COUNTERSIGN_SKIP_GATE=1 in the environment disables it (e.g. for a pure research session).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

MAX_BLOCKS = 3
TAIL_LINES = 60  # how much failing output to hand back to Claude


def repo_root(cwd: Path) -> Path | None:
    out = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )
    return Path(out.stdout.strip()) if out.returncode == 0 else None


def main() -> int:
    if os.environ.get("COUNTERSIGN_SKIP_GATE") == "1":
        return 0
    try:
        event = json.load(sys.stdin)
    except json.JSONDecodeError:
        return 0

    root = repo_root(Path(event.get("cwd") or "."))
    if root is None or not (root / "scripts" / "check.py").exists():
        return 0

    state_dir = root / ".claude" / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    counter = state_dir / f"stop-gate-{event.get('session_id', 'unknown')}.txt"
    blocks = int(counter.read_text()) if counter.exists() else 0

    result = subprocess.run(
        [sys.executable, str(root / "scripts" / "check.py"), "--changed"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode == 0:
        counter.unlink(missing_ok=True)
        return 0

    tail = "\n".join((result.stdout + result.stderr).strip().splitlines()[-TAIL_LINES:])
    if blocks >= MAX_BLOCKS:
        counter.unlink(missing_ok=True)
        print(
            json.dumps(
                {
                    "systemMessage": (
                        f"Stop gate: checks still failing after {MAX_BLOCKS} fix attempts; "
                        "letting the agent stop. Ask it what is still red."
                    )
                }
            )
        )
        return 0

    counter.write_text(str(blocks + 1))
    print(
        "You tried to finish, but `python scripts/check.py --changed` is failing "
        f"(attempt {blocks + 1} of {MAX_BLOCKS}). Fix the root cause (do not delete or skip "
        "tests, do not weaken lint rules), re-run the check, then finish.\n"
        "If you are deliberately pausing to ask the user a question, say so in one line and stop "
        f"again.\n\n{tail}",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    sys.exit(main())
