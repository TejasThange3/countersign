"""Turn off every skill this project does not need, so agents only see the relevant ones.

    python scripts/skills_filter.py

Reads the keep-list (.claude/skills-keep.txt) and the list of all known skills
(.claude/skills-catalog.txt plus whatever is installed under your Claude config dir), then writes
`skillOverrides` into .claude/settings.json with every non-kept skill set to "off".
Other keys in settings.json are preserved.

To bring a skill back: add it to .claude/skills-keep.txt and re-run this script.

Each skill is written under both its bare name (`gif`) and its claude.ai name
(`anthropic-skills:gif`), because the docs do not say which form synced skills use. Bundled
Claude Code skills (like /code-review) are never touched. Plugin skills (`engineering:*`) are not
affected by skillOverrides at all; manage those with /plugin.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SETTINGS = ROOT / ".claude" / "settings.json"
KEEP = ROOT / ".claude" / "skills-keep.txt"
CATALOG = ROOT / ".claude" / "skills-catalog.txt"
PREFIX = "anthropic-skills:"

# Names that also belong to bundled Claude Code skills; only the prefixed form is written for
# these, so the bundled command keeps working.
BUNDLED = {
    "artifact-capabilities",
    "artifact-design",
    "artifact-diagramming",
    "claude-api",
    "code-review",
    "dataviz",
    "fewer-permission-prompts",
    "init",
    "keybindings-help",
    "loop",
    "plugin-authoring",
    "run",
    "schedule",
    "security-review",
    "simplify",
    "update-config",
    "workflow-authoring",
}


def read_list(path: Path) -> set[str]:
    if not path.exists():
        return set()
    names = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            names.add(line.removeprefix(PREFIX))
    return names


def installed_skills() -> set[str]:
    config_dir = Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude")
    skills_dir = config_dir / "skills"
    names: set[str] = set()
    for base in (skills_dir, skills_dir / "synced"):
        if base.is_dir():
            names.update(p.name for p in base.iterdir() if (p / "SKILL.md").exists())
    return names


def main() -> int:
    keep = read_list(KEEP)
    every = read_list(CATALOG) | installed_skills()
    off = sorted(every - keep)

    overrides: dict[str, str] = {}
    for name in off:
        overrides[PREFIX + name] = "off"
        if name not in BUNDLED:
            overrides[name] = "off"

    settings = json.loads(SETTINGS.read_text(encoding="utf-8")) if SETTINGS.exists() else {}
    settings["skillOverrides"] = dict(sorted(overrides.items()))
    SETTINGS.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")

    missing = sorted(keep - every)
    print(f"kept {len(keep)} skills, turned off {len(off)} (written to {SETTINGS.name}).")
    if missing:
        print("note: these keep-list names were not found anywhere: " + ", ".join(missing))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
