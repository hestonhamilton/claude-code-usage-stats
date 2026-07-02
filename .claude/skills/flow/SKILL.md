---
name: flow
description: Drive the full bead loop end to end — claim, run the current R/P/I/V phase, advance through phases, and finish — pausing only at real decision boundaries. Use to work a bead (or several) with minimal prompting.
---

# flow

One command to run the bead workflow with the model in the driver's seat. It
chains the existing skills and stops only where a human decision is genuinely
required, so you are not hand-invoking `/bead-start` → `/rpiv` → `/bead-finish`
for every phase.

> Read `## Project config` in CLAUDE.md first (branch prefix, bd umbrella, verify
> command, `ENFORCEMENT`, `BEADS`). Honor every per-skill boundary below — `/flow`
> reduces prompting between steps, it does not remove the confirmation gates.

## Inputs

- Optional bead id — work that bead. Omitted: pick the first ready non-epic from
  `bd ready` (lowest available R/P/I/V phase within its epic).
- Optional `--once` — stop after the current phase instead of advancing.

## Loop

1. **Claim** — `/bead-start` for the chosen/next bead: claim it, auto-name and
   create the branch, scaffold the phase artifact.
2. **Run the phase** — `/rpiv` for the bead's current phase, under that phase's
   contract (R/P/I/V).
3. **Advance** — at a clean phase exit, transition to the next phase's bead and
   return to step 2. When an Implement phase is complete, go to step 4.
4. **Finish** — `/bead-finish`: verify against acceptance, propose a commit,
   optionally open a PR, close the bead.
5. **Next** — if ready work remains and `--once` was not given, return to step 1;
   otherwise stop and summarize what moved.

## Pause for confirmation (the only stops)

Carry over every boundary from the underlying skills — never bypass them:

- Ambiguous bead selection (only when the bead was not named explicitly).
- A foundational component/dependency choice, or an unresolved plan **Open
  Question** (`/rpiv`).
- Commit message wording, `git push`, `gh pr create`, `bd close` (`/bead-finish`).
- Any transition that changes a bead's acceptance criteria.

Between those, proceed without asking.

## Stop conditions

- Verification fails → stop at finish, report it, do not close.
- No ready work → summarize and stop.
- A boundary needs the owner → ask, then resume from the same step.
