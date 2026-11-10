# AGENTS.md — claude-usage-stats

<!-- scaffold:begin — region managed by claude-bead-scaffold. Re-running install.sh or
     /scaffold-align refreshes everything between these markers; edit project-specific
     prose outside them. -->

Instructions for coding agents (non-Claude) working in this repo. Claude reads CLAUDE.md;
this file mirrors the durable rules so any agent has them.

## Worktree + Beads

- The bd database lives in the primary repo; `bd` auto-discovers it from any
  worktree via the git common-dir, so run `bd <subcommand>` with no `-C`.
- Create worktrees with `bd worktree create <name> --branch feat/<bead-id>-<slug>`
  (a hook denies plain `git worktree add`); it wires the worktree into
  `.gitignore` and the shared beads DB.

## Branch naming (MANDATORY)

Feature branches must match `feat/<bead-id>-<kebab-slug>`.

Why: the statusline parses the bead ID, skills derive artifact paths, PR titles
come from the branch. Off-convention branches silently lose this. A hook denies
off-convention `git switch -c` / `git checkout -b` under `ENFORCEMENT=strict`
(`warn` advises instead of blocking; `off` disables it). When `BEADS=off`, the
convention drops the bead-id requirement to `feat/<kebab-slug>`.

## Workflow

- Start from `bd ready` and the `/bead-start` skill (or `/flow` to drive the whole loop).
- Use the skills (`/flow`, `/bead-start`, `/rpiv`, `/bead-finish`, `/bead-new`,
  `/security-review`, `/uiux-mock`, `/handoff-update`, `/wind-down`,
  `/skill-scout`, `/scaffold-align`) rather than ad-hoc workflows.
- Prefer small, verifiable slices with tests under the R/P/I/V phase contract.

## Code rules

- Keep secrets out of git: `.env`, credential files, keys, run logs are ignored — keep it that way.
- Verification: `.venv/bin/python -m pytest -q`.
- No AI-attribution (no Co-Authored-By trailers, no "Generated with Claude Code"
  lines) on commits or PRs; confirm before push/PR/bd close/destructive git.
- The rest of the durable rules are in `CLAUDE.md`.

<!-- scaffold:end -->


## Beads conventions

Tasks live on this repo's beads board, under the hpc board's conventions: see
`~/heston-pc/CLAUDE.md` and `~/docs/ai-ml/beads.md`. No `bd remember`, no `bd prime`
(no hook, no primer), and no bd-managed block in this file; `bd init` and `bd setup`
would add one back.
