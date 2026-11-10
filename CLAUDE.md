# CLAUDE.md — claude-usage-stats

<!-- scaffold:begin — region managed by claude-bead-scaffold. Re-running install.sh or
     /scaffold-align refreshes everything between these markers; edit project-specific
     prose outside them. -->

Instructions for Claude when working in this repo or any of its worktrees.

## Project config

Single source of truth for project-specific values. Skills and Claude read this
block; the executable half (for hooks + statusline) lives in
`.claude/scaffold.conf`. If you change a value here, mirror it there — the
`/scaffold-align` skill checks the two agree.

| Key | Value |
|---|---|
| Branch prefix | `feat/` (full form: `feat/<bead-id>-<slug>`) |
| bd umbrella | `cus` |
| Lint (on edit) | `ruff check --fix` (extensions: `py`) |
| Verification | `.venv/bin/python -m pytest -q` |
| Enforcement | `warn` (`strict` blocks · `warn` advises · `off` silent) |
| Beads | `on` (`on` = bead-tracked workflow · `off` = beads-agnostic) |

## Repo

Multi-machine Claude Code usage & cost dashboard (FastAPI + SQLite)

Work is tracked in beads under the `cus` umbrella.

## Branch naming

`feat/<bead-id>-<kebab-slug>` — e.g. `feat/<bead-id>-research-tech-stack`.

The statusline parses the bead ID from the branch and skills derive artifact
paths from it; off-convention branches silently lose that wiring. A hook denies
off-convention `git switch -c` / `git checkout -b` (under `ENFORCEMENT=warn` it
advises instead of blocking; `off` disables the check). Grandfather legacy
branches via `BRANCH_GRANDFATHER` in `.claude/scaffold.conf`. When `BEADS=off`,
the convention drops the bead-id requirement to `feat/<kebab-slug>`.

## Beads

- Single bd database in the primary repo. `bd` auto-discovers it from any
  worktree via the git common-dir, so just run `bd <subcommand>` — no `-C` needed.
- Create worktrees with `bd worktree create <name> --branch feat/<bead-id>-<slug>`
  (a hook denies plain `git worktree add`).
- Pick work from `bd ready`.

## Skills

Live in `.claude/skills/`. Invoke as `/<name>`:

- Driver: `/flow` (runs the whole bead loop, pausing only at decision points).
- Bead workflow: `/bead-start`, `/rpiv`, `/bead-finish`, `/bead-new`.
- Audits: `/security-review`, `/uiux-mock`.
- Session: `/handoff-update`, `/wind-down`, `/skill-scout`.
- Scaffold: `/scaffold-align` (run after installing or re-configuring the scaffold).

## Doc format

Generated **reference/spec** artifacts are authored as self-contained HTML so they
can carry richer visual structure (tradeoff matrices, badges, acceptance grids,
diagrams). This applies to:

- Research docs — `docs/<id>-research.html`
- Plan docs — `docs/<id>-plan.html`
- ADRs — `docs/adr/<n>-<slug>.html` (copy `docs/adr/0000-template.html`)
- uiux decision docs — `docs/<id>-uiux.html`
- security-review findings, when persisted — `docs/<id>-security-review.html`

Stay **markdown** (terminal-/GitHub-read, frequently diffed, or transcript-shaped):
this file, `AGENTS.md`, `HANDOFF.md`, verification docs (`docs/<id>-verification.md`),
and bead notes.

Conventions:

- **Self-contained**: one HTML file, inline `<style>`, no CDN, no framework.
  Opens with `xdg-open <file>` or `python -m http.server`.
- **Start from `docs/_doc-template.html`** — copy it, fill the content, keep the
  embedded token block so docs stay visually consistent.
- **Earn the HTML**: reach for the visual vocabulary only where structure adds
  leverage. A prose-only doc can stay markdown.
- **Tradeoff to accept**: GitHub renders committed `.html` as source. Review
  these docs by opening them, not in the PR diff.

## Hooks

Configured in `.claude/settings.json` (sourcing `.claude/scaffold.conf`). The
`ENFORCEMENT` mode applies to the first two (strict = deny, warn = advise, off =
silent):

- Blocks AI-attribution (`Co-Authored-By` trailers and `Generated with Claude Code`
  lines) in commits and PR bodies.
- Blocks off-convention branch creation and (when `BEADS=on` and
  `WORKTREE_GUARD=bd`) plain `git worktree add`.
- Runs the configured lint-fix command on edited source files (independent of
  `ENFORCEMENT`).
- On a cold start, injects a compact orientation block (branch, bead, `bd ready`,
  HANDOFF priority); before compaction, snapshots state and re-injects it
  afterward. Subagent-safe and gated by `SESSION_ORIENT` in `.claude/scaffold.conf`.
  The HANDOFF priority line is gated by the `HANDOFF` dial — set `HANDOFF=off` for
  a bd-only knowledge convention (no `HANDOFF.md`/`MEMORY.md`); install then skips
  `HANDOFF.md` and the orient hook omits that line.

## Verification

Run the project's verification commands (see `## Project config`):

```bash
.venv/bin/python -m pytest -q
```

## Rules

- No AI-attribution: no `Co-Authored-By` trailers and no "Generated with Claude
  Code" lines on commits or PRs.
- Confirm before `git push`, `gh pr create`, `bd close`, or any destructive git op.
- `.env`, secrets, credential files, and run logs stay out of git (`.gitignore`
  is the source of truth).
- Preserve HANDOFF.md sections that aren't yours to own.

<!-- scaffold:end -->



## Beads conventions

Tasks live on this repo's beads board, under the hpc board's conventions: see
`~/heston-pc/CLAUDE.md` and `~/docs/ai-ml/beads.md`. No `bd remember`, no `bd prime`
(no hook, no primer), and no bd-managed block in this file; `bd init` and `bd setup`
would add one back.
