---
name: scaffold-align
description: After dropping the claude-bead-scaffold bundle into a project, verify it is filled in, wired correctly, internally consistent, and matched to this project's actual stack and conventions. Run once right after install, and again whenever the stack or branch convention changes.
---

# scaffold-align

Make the generic scaffold fit *this* project. Detect the project's real stack and
conventions, compare them against what the bundle declares, report every gap, and
apply fixes only on confirmation.

This skill is read-mostly: it inspects and reports first, then proposes a concrete
change set. Never silently rewrite config — the owner approves the diff.

## What "aligned" means

0. **Pending brownfield merges resolved.** No `*.scaffold-new` sidecars or a
   `.scaffold-merge-pending` file remain unmerged (see "Brownfield merge" below).
   Any `CLAUDE.md`-is-a-symlink and bd-managed-doc-region situations are resolved.
1. **No leftover placeholders.** No `{{...}}` tokens remain in CLAUDE.md, AGENTS.md, HANDOFF.md.
2. **Two-form config agrees.** Values in `.claude/scaffold.conf` match the `## Project config` block in CLAUDE.md (branch prefix, lint, verification, `ENFORCEMENT`, `BEADS`).
3. **Config matches reality.** `LINT_CMD`/`LINT_EXTS` and the verification command match the project's actual language, test runner, and linter, and `LINT_CMD`'s binary actually **resolves** (venv / `node_modules/.bin` / PATH). `BEAD_ID_REGEX` matches the ids `bd` actually issues.
4. **Hooks are live.** Hook + statusline scripts exist, are executable, and are referenced in `.claude/settings.json`. The merge didn't drop a pre-existing hook or duplicate one.
5. **Beads status is known.** Either `bd` is usable here (on PATH, DB reachable, the `## Project config` umbrella exists) **or** the precise blocker is reported: `bd` not installed, vs. `bd` present but its DB/backend is unreachable (a *blocked*, not *failed*, state — don't flip `BEADS=off` for it).
6. **Docs convention is real.** `docs/_doc-template.html` exists; the doc-format section in CLAUDE.md points at paths that make sense for this repo.

## Steps

### 0. Brownfield merge (only if pending)

When the installer drops into a repo that already had a `CLAUDE.md`/`AGENTS.md`
without scaffold markers, it leaves the original untouched and writes the
scaffold version beside it as `<file>.scaffold-new`, listing the files in
`.scaffold-merge-pending`. Reconcile these *before* the rest of alignment:

- For each pending file, **read both** the existing file and its `.scaffold-new`
  sibling and **merge intent**, don't blindly concatenate:
  - Keep the project's own content and voice.
  - Fold in the scaffold's distinct contributions (the `## Project config` block,
    skills/hooks/doc-format pointers, R/P/I/V workflow notes).
  - Where both cover the same ground (branch naming, commit rules), reconcile into
    one coherent statement rather than duplicating — prefer the project's existing
    convention and note any genuine conflict for the owner.
  - Wrap the scaffold-managed portion in `<!-- scaffold:begin -->` …
    `<!-- scaffold:end -->` so future updates stay surgical.
- Show the proposed merged file as a diff. **On confirmation**, write it, then
  delete the `.scaffold-new` sidecar. When all are merged, remove
  `.scaffold-merge-pending`.
- Never delete a `.scaffold-new` or the original without applying an approved merge.

**First check two layout traps the scaffold's two-file model can hit:**

- **`CLAUDE.md` is a symlink (commonly → `AGENTS.md`).** The repo treats them as
  one file; the scaffold treats them as two. `test -L CLAUDE.md` to detect.
  Raise this as a decision (`AskUserQuestion`) before merging:
  - **(a) Keep one file** — leave the symlink, inject a single `scaffold:begin/end`
    region into the real target (`AGENTS.md`), and drop the redundant sidecar.
  - **(b) Split into two real files** — replace the symlink with a real `CLAUDE.md`
    (full: project config + the repo's rich content) and reduce `AGENTS.md` to the
    thin durable-rules mirror. Back up the original first.
  Apply the chosen shape; don't write *through* a symlink assuming two files.

- **A `bd`-managed region already exists.** Look for `<!-- BEGIN BEADS INTEGRATION`
  … `<!-- END BEADS INTEGRATION -->` (injected and hash-tracked by `bd` itself).
  Treat it as externally owned: **leave it intact** and **do not duplicate** the
  beads / worktree / session-completion content it already provides when folding
  in the scaffold region. The scaffold region should add only what bd's block
  doesn't (e.g. the `## Project config` table, skills list, doc-format, hooks).
  If you relocate that block (e.g. when splitting the symlink), warn the owner
  that `bd` may re-inject it into its original file on the next bd doc-sync.

### 1. Detect project facts (read-only)

- Language / package manager: presence of `pyproject.toml`, `package.json`, `go.mod`, `Cargo.toml`, `pom.xml`, etc.
- Test runner: scripts in `package.json`, `[tool.pytest]`/`pytest` in `pyproject.toml`, a `Makefile` `test:` target, `go test`, etc.
- Linter/formatter: `ruff`/`flake8`/`black`, `eslint`/`prettier`, `gofmt`, `clippy` — config files or dev-deps.
- Local tool dirs: `.venv/`, `.test.venv/`, `node_modules/.bin/`.
- Git: base branch (`git symbolic-ref refs/remotes/origin/HEAD` or fallback `main`/`master`), remote present?
- Beads — resolve to one of three states: **(a)** `bd` not on PATH (`command -v bd` fails); **(b)** `bd` present but `bd ready`/`bd list` errors (DB/backend unreachable — e.g. the engine isn't installed or the server is down); **(c)** works — note the id format existing beads use.
- Layout traps: is `.claude/skills` a symlink (`test -L`)? is `CLAUDE.md` a symlink, and to what (`readlink`)? does a doc carry a `<!-- BEGIN BEADS INTEGRATION` block?
- Existing harness: was there a `CLAUDE.md` / `.claude/settings.json` *before* the bundle? Check `git log`/`git status` for whether install backed something up (`*.scaffold-bak`).

### 2. Read what the bundle declares

- `.claude/scaffold.conf` — `ENFORCEMENT`, `BEADS`, `BRANCH_PREFIX`, `BEAD_ID_REGEX`, `BRANCH_GRANDFATHER`, `WORKTREE_GUARD`, `STATUSLINE_USAGE`, `LINT_CMD`, `LINT_EXTS`.
- `## Project config` block in CLAUDE.md — the human-facing table.
- `.claude/settings.json` — statusLine + hook wiring + permissions.

### 3. Compute the gap list

For each "aligned" criterion above, produce **pass / fix-needed** with one line of evidence. Concrete checks:

- `grep -rl '{{' CLAUDE.md AGENTS.md HANDOFF.md` → any hit is a fix.
- Cross-check scaffold.conf values against the CLAUDE.md table → mismatches are fixes.
- **Lint binary resolves?** Resolve `LINT_CMD`'s first word the way the hook does:
  `.venv/bin/`, `.test.venv/bin/`, the **git/workspace-root** `node_modules/.bin/`,
  the nearest `node_modules/.bin/`, then PATH. If it resolves nowhere, the
  PostToolUse lint hook silently no-ops — **warn once** with the reason (e.g.
  "`prettier` not found — run `pnpm install`", or "binary missing; check `LINT_CMD`").
  Separately, if the binary isn't installed **and** the detected language differs
  from `LINT_EXTS` → propose the right command/exts for the stack (`eslint --fix` +
  `ts tsx js jsx`; `gofmt -w` + `go`).
- If the verification command in `## Project config` doesn't match the detected test runner → propose the detected one.
- **Bead-id regex (only if `bd` is usable — state (c)):** sample real ids
  (`bd list --json` if supported, else `bd list`), test `BEAD_ID_REGEX` against
  one, and propose the matching regex on mismatch — note that the default assumes
  a **numeric** suffix, so alpha/compound ids (`pct-l3l`, `pct-mol-gyqx`, dotted
  `pct-7f2r.3`) need e.g. `pct-[a-z0-9-]+(\.[0-9]+)*`. If `bd` is in state (a)/(b),
  this check is **blocked** — report it can't be validated yet, don't guess.
- **Adoption fit (brownfield):** if most existing branches are off-convention (sample `git branch --format='%(refname:short)'`), `ENFORCEMENT=strict` will block routine work — propose `warn` and offer to seed `BRANCH_GRANDFATHER` from the existing patterns. Propose `BEADS=off` only when the repo genuinely doesn't use beads (`bd` absent **and** no `.beads/`) — **not** when beads are configured but the backend is merely down (state (b)). Cross-check that `ENFORCEMENT`/`BEADS` in `scaffold.conf` match the `## Project config` table.
- **Version drift:** compare `SCAFFOLD_VERSION` in `scaffold.conf` against the bundle's `VERSION`. If the bundle is newer, offer the **lighter update path** — re-run `install.sh -y <repo>` (it refreshes the scaffold marker regions, hooks, statusline, and skills in place without re-prompting) — rather than reconfiguring by hand. If the bundle is unavailable locally, just report the drift.
- For each hook/statusline path in settings.json: file exists? `test -x`? If not executable → fix is `chmod +x`.
- Detect a clobbered/duplicated merge: are there two PreToolUse Bash blocks, or a pre-existing hook that's now missing? Look for a `*.scaffold-bak` settings file and diff.
- Beads state: `command -v bd`, then `bd ready`. State (c) → check the
  `## Project config` umbrella is present in `bd list`. State (b) → report
  "blocked: bd present, backend unreachable" with the failing command's hint.
  State (a) → report "bd not installed".

### 4. Report

Print a compact table: criterion → verdict → evidence → proposed fix. Group fixes into:
- **Auto-applicable** (chmod, token fills, conf↔CLAUDE.md sync, lint/verify command swap).
- **Needs a decision** (umbrella doesn't exist; base branch ambiguous; multiple languages detected) — raise these via `AskUserQuestion`.

### 5. Apply (on confirmation)

- Apply auto-applicable fixes with Edit (keep scaffold.conf and the CLAUDE.md table in sync — change both).
- `chmod +x` any non-executable hook/statusline scripts.
- For decisions, apply the user's chosen answers.
- Re-run step 3's checks and confirm every criterion now passes; print the residual list if any remain.

### 6. Smoke-test the wiring (optional, ask first)

- Lint hook: confirm `auto-lint.sh` resolves the binary (dry: print which path it would use — venv / workspace-root `node_modules/.bin` / nearest / PATH). If nothing resolves, say so plainly: the hook will no-op until the binary is installed.
- Branch guard: echo a deliberately-bad branch name through the guard's regex and confirm it would be denied; echo a good one and confirm allowed. (Validate the regex, don't actually create branches.)
- Statusline: pipe a minimal stub JSON to `statusline.sh` and confirm it prints a line without error.

## Boundaries (pause for confirmation)

- Any edit to CLAUDE.md / AGENTS.md / scaffold.conf / settings.json.
- Creating a bd umbrella or any bead.
- Deleting a `*.scaffold-bak` backup (never delete without asking).
- Committing — leave that to the user / `bead-finish`.
