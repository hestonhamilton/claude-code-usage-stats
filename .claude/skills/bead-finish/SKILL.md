---
name: bead-finish
description: Verify the active bead against its acceptance criteria using the project's standard checks, append a notes block to the bead, propose a commit (no co-author), optionally open a PR, and close the bead. Use when implementation for a bead feels complete.
---

# bead-finish

Autonomous within the bead; confirm at commit/push/PR/close boundaries.

> Read the `## Project config` block in CLAUDE.md for this project's verification commands and commit rules before step 3.

## Inputs

- Optional bead ID; defaults to the bead matching the current branch via `<BRANCH_PREFIX><id>-...`.

## Steps

1. Pull the bead's acceptance criteria: `bd show <id>`. Restate them in a numbered checklist.
2. For each acceptance bullet, state which test / file / behavior demonstrates it. If a bullet is unverified, **stop** and ask the user how to verify; do not proceed to close.
3. Run the project's verification commands (from `## Project config`). Capture pass counts and any lint diagnostics.
4. If verification fails, report the failure and stop — do not propose commit or close.
5. Append to the bead: `bd note <id> --message "Verification: <results>. Files: <list>. Commands: <list>."`.
6. Propose a commit message (1–2 sentences, why-focused, no co-author). Wait for approval, then commit via HEREDOC.
7. Ask whether to push and open a PR. If yes: `gh pr create` with title `<bead-id>: <short title>` and a body containing Summary + Test plan + link to acceptance.
8. After PR (or skip), ask whether to close the bead. On confirmation: `bd close <id> -r "<verification summary>"`.
9. Print newly unblocked beads (`bd ready`), or close with `--claim-next` to auto-advance.

## Boundaries (pause for confirmation)

- Commit message wording.
- `git push`.
- `gh pr create`.
- `bd close`.
