@AGENTS.md

## Claude Code specifics

- Subagents in `.claude/agents/`: `reviewer` (step 4 of the done loop), `test-writer`,
  `researcher` (read-only docs/SDK questions). Use them; they start with a fresh context and
  their own skills.
- Hooks in `.claude/settings.json` lint every Python edit and block finishing while
  `scripts/check.py --changed` is red. If the Stop gate blocks you, fix the cause. Don't work
  around it.
- Only the project-relevant skills are enabled (see `.claude/skills-keep.txt`). Prefer `tdd`,
  `grill-me`, `diagnosing-bugs`, `verification-before-completion` and `code-review`.
