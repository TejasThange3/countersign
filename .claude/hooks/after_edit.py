"""Feedback loop 1 (PostToolUse on Edit|Write): instant lint on the file Claude just edited.

Auto-fixes what ruff can fix (formatting, import order, simple lint), then reports anything left
back to Claude via stderr + exit code 2, so the agent fixes it in the same turn instead of
discovering it at the end.

Silent (exit 0) for non-Python files and when everything is clean.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

RUFF = "ruff@0.17.0"  # keep in sync with scripts/check.py


def main() -> int:
    try:
        event = json.load(sys.stdin)
    except json.JSONDecodeError:
        return 0
    file_path = (event.get("tool_input") or {}).get("file_path") or ""
    path = Path(file_path)
    if path.suffix != ".py" or not path.exists():
        return 0

    uvx = shutil.which("uvx")
    if not uvx:
        return 0  # tooling missing; the Stop gate and CI will still catch problems

    cwd = Path(event.get("cwd") or path.parent)
    result = subprocess.run(
        [uvx, RUFF, "check", "--fix", "--quiet", "--output-format", "concise", str(path)],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )
    # Format after fixing, so removed imports don't leave stray blank lines.
    subprocess.run([uvx, RUFF, "format", "--quiet", str(path)], cwd=cwd, check=False)
    if result.returncode != 0:
        print(
            f"ruff found problems it could not auto-fix in {path.name}. Fix them now:\n"
            f"{result.stdout.strip()}",
            file=sys.stderr,
        )
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
