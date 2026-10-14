"""The one command that answers "is the code healthy?".

Used by agents before they say "done", by the Stop hook (feedback loop 2) and by CI.

    python scripts/check.py            # check every project
    python scripts/check.py --changed  # only projects with changes vs main (fast, used by hooks)
    python scripts/check.py --integration  # also run tests marked `integration` (needs Docker)

Live tests (marked `live`, they call real ArmorIQ/ElevenLabs/Gemini) are never run here;
run them on purpose with `uv run --project <dir> pytest -m live`.

Standard library only, so it runs anywhere Python 3.11+ and uv are installed.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

# Single pin for the linter, shared by hooks, agents and CI.
RUFF = "ruff@0.17.0"

ROOT = Path(__file__).resolve().parent.parent
# Directories that may hold Python projects (anything with a pyproject.toml directly inside).
PROJECT_PARENTS = ["apps", "spikes"]
STANDALONE_PROJECTS = ["evals"]
DASHBOARD = ROOT / "apps" / "dashboard"
# Repo tooling that is not a uv project but still gets linted.
TOOLING = ["scripts", ".claude/hooks"]


def find_python_projects() -> list[Path]:
    projects = [ROOT / p for p in STANDALONE_PROJECTS if (ROOT / p / "pyproject.toml").exists()]
    for parent in PROJECT_PARENTS:
        base = ROOT / parent
        if base.is_dir():
            projects += sorted(p for p in base.iterdir() if (p / "pyproject.toml").exists())
    return projects


def git(*args: str) -> list[str]:
    out = subprocess.run(
        ["git", *args], cwd=ROOT, capture_output=True, text=True, check=False
    ).stdout
    return [line.strip() for line in out.splitlines() if line.strip()]


def changed_files() -> list[str]:
    """Files changed on this branch vs main, plus uncommitted and untracked files."""
    files: set[str] = set()
    base = git("merge-base", "HEAD", "main")
    if base:
        files.update(git("diff", "--name-only", base[0], "HEAD"))
    files.update(git("diff", "--name-only", "HEAD"))
    files.update(git("ls-files", "--others", "--exclude-standard"))
    return sorted(files)


def is_under(path: str, project: Path) -> bool:
    rel = project.relative_to(ROOT).as_posix() + "/"
    return path.replace("\\", "/").startswith(rel)


def run(label: str, cmd: list[str], cwd: Path, ok_codes: tuple[int, ...] = (0,)) -> bool:
    print(f"\n--- {label}: {' '.join(cmd)}", flush=True)
    exe = shutil.which(cmd[0]) or cmd[0]
    result = subprocess.run([exe, *cmd[1:]], cwd=cwd, check=False)
    passed = result.returncode in ok_codes
    print(f"--- {label}: {'PASS' if passed else f'FAIL (exit {result.returncode})'}", flush=True)
    return passed


def check_python(project: Path, integration: bool) -> list[str]:
    name = project.relative_to(ROOT).as_posix()
    failures = []
    if not run(f"{name} lint", ["uvx", RUFF, "check", "."], project):
        failures.append(f"{name}: ruff check")
    if not run(f"{name} format", ["uvx", RUFF, "format", "--check", "."], project):
        failures.append(f"{name}: ruff format --check (run `uvx {RUFF} format {name}`)")
    marker = "not live" if integration else "not live and not integration"
    # pytest exit code 5 = no tests collected; acceptable for a brand-new project.
    if not run(
        f"{name} tests",
        ["uv", "run", "--project", ".", "pytest", "-q", "-m", marker],
        project,
        ok_codes=(0, 5),
    ):
        failures.append(f"{name}: pytest")
    return failures


def check_tooling() -> list[str]:
    failures = []
    if not run("tooling lint", ["uvx", RUFF, "check", *TOOLING], ROOT):
        failures.append("scripts/.claude hooks: ruff check")
    if not run("tooling format", ["uvx", RUFF, "format", "--check", *TOOLING], ROOT):
        failures.append(f"scripts/.claude hooks: ruff format --check (run `uvx {RUFF} format`)")
    return failures


def check_dashboard() -> list[str]:
    if not (DASHBOARD / "package.json").exists() or not (DASHBOARD / "node_modules").exists():
        return []
    failures = []
    for script in ("lint", "typecheck"):
        if not run(f"dashboard {script}", ["npm", "run", "--if-present", script], DASHBOARD):
            failures.append(f"apps/dashboard: npm run {script}")
    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--changed", action="store_true", help="only projects changed vs main")
    parser.add_argument("--integration", action="store_true", help="include integration tests")
    args = parser.parse_args()

    projects = find_python_projects()
    include_dashboard = include_tooling = True
    if args.changed:
        files = changed_files()
        projects = [p for p in projects if any(is_under(f, p) for f in files)]
        include_dashboard = any(is_under(f, DASHBOARD) for f in files)
        include_tooling = any(is_under(f, ROOT / t) for f in files for t in TOOLING)
        if not projects and not include_dashboard and not include_tooling:
            print("check: no project files changed vs main; nothing to check.")
            return 0

    failures: list[str] = []
    for project in projects:
        failures += check_python(project, args.integration)
    if include_tooling:
        failures += check_tooling()
    if include_dashboard:
        failures += check_dashboard()

    print("\n=== check summary ===")
    if failures:
        for failure in failures:
            print(f"FAIL  {failure}")
        return 1
    print("PASS  everything checked is green")
    return 0


if __name__ == "__main__":
    sys.exit(main())
