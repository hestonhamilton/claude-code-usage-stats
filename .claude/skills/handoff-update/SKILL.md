---
name: handoff-update
description: Refresh HANDOFF.md with current branch state, beads completed this session, latest verification command output, and next-session priority. Use at the end of a work session or before context handoff.
---

# handoff-update

Autonomous; confirm before overwriting HANDOFF.md if its current content has changes not made by the assistant this session.

## HANDOFF.md structure (convention)

1. `# Handoff`
2. `## Current Branch`
3. `## Start Here` — numbered steps (read AGENTS.md, check `bd ready`).
4. `## Completed This Session` — closed beads with one-line descriptions.
5. `## Current Ready Work` — the next bead to claim.
6. `## Next Session Priority` — prose on what to prioritize and why.
7. `## Verification` — the standard command suite plus latest run results.
8. `## Commit Status` — committed/pushed vs in-progress.

## Steps

1. Read the current HANDOFF.md; preserve sections we don't own (it may have drifted).
2. Compute state: `git branch --show-current`, `git status --short`, recent closed beads (`bd list` filtered), `bd ready`.
3. Determine the next ready bead the next session should claim.
4. Compose the **Next Session Priority** paragraph: what changed, what blocked, what to do first.
5. Re-run the project's verification commands (only if work was done this session); record pass counts verbatim.
6. Update each section, preserving content outside this skill's domain. Use Edit, not Write, unless restructuring.
7. Surface `git diff HANDOFF.md` before suggesting a commit.

## Style

- No emoji.
- Section headers stay `##` and in order.
- Quote bd IDs in their canonical form, not free-form names.

## Boundaries (pause for confirmation)

- Removing any pre-existing section.
- Committing HANDOFF.md changes.
- Pushing.
