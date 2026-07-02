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


<!-- BEGIN BEADS INTEGRATION v:1 profile:minimal hash:7510c1e2 -->
## Beads Issue Tracker

This project uses **bd (beads)** for issue tracking. Run `bd prime` to see full workflow context and commands.

### Quick Reference

```bash
bd ready              # Find available work
bd show <id>          # View issue details
bd update <id> --claim  # Claim work
bd close <id>         # Complete work
```

### Rules

- Use `bd` for ALL task tracking — do NOT use TodoWrite, TaskCreate, or markdown TODO lists
- Run `bd prime` for detailed command reference and session close protocol
- Use `bd remember` for persistent knowledge — do NOT use MEMORY.md files

**Architecture in one line:** issues live in a local Dolt DB; sync uses `refs/dolt/data` on your git remote; `.beads/issues.jsonl` is a passive export. See https://github.com/gastownhall/beads/blob/main/docs/SYNC_CONCEPTS.md for details and anti-patterns.

## Session Completion

**When ending a work session**, you MUST complete ALL steps below. Work is NOT complete until `git push` succeeds.

**MANDATORY WORKFLOW:**

1. **File issues for remaining work** - Create issues for anything that needs follow-up
2. **Run quality gates** (if code changed) - Tests, linters, builds
3. **Update issue status** - Close finished work, update in-progress items
4. **PUSH TO REMOTE** - This is MANDATORY:
   ```bash
   git pull --rebase
   git push
   git status  # MUST show "up to date with origin"
   ```
5. **Clean up** - Clear stashes, prune remote branches
6. **Verify** - All changes committed AND pushed
7. **Hand off** - Provide context for next session

**CRITICAL RULES:**
- Work is NOT complete until `git push` succeeds
- NEVER stop before pushing - that leaves work stranded locally
- NEVER say "ready to push when you are" - YOU must push
- If push fails, resolve and retry until it succeeds
<!-- END BEADS INTEGRATION -->
