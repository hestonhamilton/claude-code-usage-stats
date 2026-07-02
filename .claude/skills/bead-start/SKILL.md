---
name: bead-start
description: Claim the next ready bead (or a named one), set state to in_progress, surface acceptance criteria, create a feature branch, and scaffold the artifact path for the bead's R/P/I/V phase. Use at the start of any work session.
---

# bead-start

Autonomous within the bead; confirm at branch-name/PR/close boundaries.

> Read the `## Project config` block in CLAUDE.md first — it defines the branch prefix, bd umbrella, and doc/verification conventions this skill relies on.

## Repo facts (do not re-derive)

- Single bd database in the primary repo. `bd` auto-discovers it from any worktree via the git common-dir, so just run `bd <subcommand>` — no `-C` needed.
- Worktrees live alongside the primary repo; create them with `bd worktree create <name> --branch <BRANCH_PREFIX><bead-id>-<slug>`.

## Inputs

- Optional positional: a bead ID. If omitted, pick the first ready non-epic from `bd ready` (lowest available R/P/I/V phase within its epic).

## Steps

1. `bd show <id>` — print title, acceptance, deps, parent.
2. Confirm with the user the chosen bead matches their intent (one sentence; skip if they named it explicitly).
3. `bd update <id> --claim` — atomically sets status to `in_progress` and assigns the issue to you.
4. Branch naming: derive the canonical name `<BRANCH_PREFIX><bead-id>-<kebab-slug>` from the bead id + a kebab slug of its title (prefix from `## Project config`; truncate at ~60 chars) and **create it without asking** — the branch hook enforces the convention, so a bad name is caught, not silently accepted. Only pause to confirm when the title is empty/ambiguous or the slug needs a judgment call.
5. Scaffold the artifact for the phase (reference/spec docs are HTML, copied from `docs/_doc-template.html`; see CLAUDE.md "## Doc format"):
   - **R**: `docs/<bead-id>-research.html` — sections: Context, Options, Recommendation, Open questions.
   - **P**: `docs/<bead-id>-plan.html` — sections: Goal, Steps, Risks/rollback, Acceptance mapping.
   - **I**: no doc; surface the matching `.P` plan as the working contract.
   - **V**: `docs/<bead-id>-verification.md` (markdown) — Acceptance checklist, Commands run, Results, Sign-off.
6. Print: bead summary, branch, artifact path, the next 3 acceptance bullets, and `bd ready` minus this bead.

## Boundaries (pause for confirmation)

- Branch creation only when the slug is ambiguous (otherwise auto-named, since the hook enforces the convention).
- Any `bd close` (use `bead-finish`).
- Any `git push` or PR open.
