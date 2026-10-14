# Task cards

One file per lane. An agent's first message is: "Read tasks/<lane>.md and AGENTS.md. Show me your plan before editing."

A task card must be committed to main **before** you start the lane's worktree. A new worktree only contains committed files.

## Template

```markdown
# Lane: <name>

TASK: <one or two sentences>
CONTEXT: <scope doc sections to read, other notes>
FILES YOU OWN: <globs>
DO NOT TOUCH: everything else (root files belong to the main session; see AGENTS.md)
HUMAN STEPS: <things only the user can do, e.g. console clicks, API keys>; ask, then wait
DONE MEANS:
- <checkable outcome 1>
- <checkable outcome 2>
- `python scripts/check.py --changed` green, reviewer PASS, Codex review PASS (max 3 rounds)
- notes-drafts/<name>.md written in the AGENTS.md notes format
Start by showing me your plan before editing.
```

## Rules for splitting work

- Two lanes never own the same file. If two tasks need the same file, run them one after another.
- Read-only lanes (research, "explain this module") are safe to run alongside anything.
- Start with 3 lanes. Reviewing their output is the bottleneck, not starting them.
