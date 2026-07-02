---
name: wind-down
description: Snapshot an in-progress bead so work can resume cleanly later. Adds a bead note, stabilizes the working tree (wip commit or stash), updates HANDOFF.md.
---

# wind-down

## Inputs
- Optional bead ID (default: parse from current branch `<BRANCH_PREFIX><bead-id>-…`).
- Optional reason: `eos` | `pivot` | `blocked` | `handoff` (default `eos`).

## Steps

1. Identify the active bead. `bd show <id>`.
2. Snapshot: `git status --short`, `git log <base>..HEAD --oneline`, last section of the phase artifact (`docs/<id>-*`).
3. Draft a wind-down note answering: **Done**, **Not done / next action**, **Open questions**, **Resume entry point (branch + file:line or command)**. Confirm wording, then `bd note <id> --message "<note>"`.
4. Stabilize the tree — confirm one of:
   - `git commit -m "wip: <id> <summary>"` (default for `eos`/`handoff`; `wip:` bypasses the bead-id branch hook concern since it's a commit, not a branch).
   - `git stash push -u -m "wip:<id>:<reason>"` (default for `pivot`).
   - Leave dirty (only if user asks; warn).
5. Update HANDOFF.md (or invoke `handoff-update`).
6. Print: bead id + phase, note summary, tree disposition, **resume command** for next session.

## Boundaries

- Confirm before: bead note wording, commit message, any `git push`, any `bd update` status change.
- Never delete the branch — that belongs to `bead-finish`.
