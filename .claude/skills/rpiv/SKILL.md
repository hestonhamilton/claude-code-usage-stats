---
name: rpiv
description: Detect which phase (Research / Plan / Implement / Verify) the active bead is in and run that phase with the right artifact shape. Use to keep work disciplined to the R/P/I/V pattern instead of conflating phases.
---

# rpiv

Autonomous within the phase; confirm at phase-exit (handing off to the next phase's bead).

> See the doc-format convention and `## Project config` in CLAUDE.md for artifact paths and verification commands.

## Phase detection

Read the active bead's title/phase tag (`R`/`P`/`I`/`V`). If the active bead has no phase (i.e. it's an epic), refuse and ask the user to pick or create the appropriate phase child via `bead-new`.

## Phase contracts

### R — Research
- **Kickoff (required, before deep research)**: identify the highest-leverage unknowns — constraints, host/hardware reality, the owner's existing preferences/biases, scope boundaries, and any assumptions baked into the bead's framing — and surface 1–3 of them via `AskUserQuestion` *before* investing in research. Directing the research early avoids rework; treat this as a critical step, not a courtesy.
- **Stance**: challenge the assumptions in the bead's framing — don't treat a pre-supplied option list as the whole decision space. Weight maturity and documentation/example depth as a hard selection criterion; bleeding-edge tools with thin docs must clear a high bar.
- **Artifact**: `docs/<bead-id>-research.html` — self-contained HTML, copied from `docs/_doc-template.html`.
- **Sections**: Context, Options (≥2, with tradeoffs), Recommendation, Open questions. Render Options as a tradeoff table and flag the pick with a recommendation badge. Record the owner's kickoff answers in the doc.
- **Allowed tools**: Read, Grep, WebFetch, WebSearch, Explore subagent, AskUserQuestion.
- **Forbidden**: writing implementation code, committing migrations, modifying configs.
- **Exit**: research doc committed. Propose creating/transitioning the matching `.P` bead.

### P — Plan
- **Artifact**: `docs/<bead-id>-plan.html` — self-contained HTML, copied from `docs/_doc-template.html`.
- **Sections**: Goal, Step list (each step ≤1 PR-sized chunk), Risks + rollback, Acceptance mapping (which step satisfies which acceptance bullet). Render the Acceptance mapping as a step→bullet table.
- **Allowed**: writing the plan doc, refining the matching `.I` and `.V` bead acceptance via `bd update`.
- **Forbidden**: writing implementation code; silently "pinning" a foundational component as a default. Any unresolved component/dependency selection must be recorded as a **decision needing owner sign-off**, not a placeholder that later hardens.
- **Exit**: plan doc committed. Surface refined `.I` acceptance for sign-off.

### I — Implement
- **Artifact**: code + tests + migrations.
- **Working contract**: the matching `.P` bead's plan doc. Quote step numbers as you complete them.
- **Forbidden**: scope expansion not in the plan; if the plan is wrong, **stop**, update the plan doc, then resume. Also forbidden: silently resolving a plan **Open Question** or hardening a soft-default component choice into code — **stop and surface it** for sign-off first.
- **Exit**: tests green locally, lint clean. Hand off to `bead-finish` for verification + commit.

### V — Verify
- **Artifact**: `docs/<bead-id>-verification.md` (stays markdown — command transcripts).
- **Sections**: Acceptance checklist (each bullet ticked or explained), Commands run (verbatim + truncated output), Observations, Sign-off.
- **Allowed**: running tests, manual UI/API exercises, reading logs.
- **Forbidden**: fixing bugs in V — bugs found during V become new beads or reopen `.I`.
- **Exit**: verification doc committed, parent epic eligible for close.

## Boundaries (pause for confirmation)

- Phase transitions (R→P, P→I, I→V).
- Modifying acceptance criteria on any bead.
- Creating new beads as a side effect of the current phase.
- **Selecting or swapping any foundational component/dependency** (reverse proxy/web server, database, queue, language/framework, base image, auth model, TLS strategy). Surface the choice **and its rationale** for sign-off before baking it in, even mid-Implement.
