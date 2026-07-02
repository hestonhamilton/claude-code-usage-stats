#!/usr/bin/env bash
# PreCompact hook. PreCompact cannot inject context forward, so this writes a
# small state snapshot to a per-project cache file; the SessionStart hook
# re-injects it after compaction (source=compact). Side-effect only, never blocks.
# Subagent-safe and gated by SESSION_ORIENT in .claude/scaffold.conf.
set -uo pipefail

input="$(cat 2>/dev/null || true)"

agent_id="$(printf '%s' "$input" | jq -r '.agent_id // empty' 2>/dev/null)"
[ -n "$agent_id" ] && exit 0

cwd="$(printf '%s' "$input" | jq -r '.cwd // .workspace.current_dir // empty' 2>/dev/null)"
[ -n "$cwd" ] && cd "$cwd" 2>/dev/null || true

SESSION_ORIENT="on"; BEADS="on"; BEAD_ID_REGEX='[a-z0-9]+-[0-9]+(\.[0-9]+)*'
conf="${CLAUDE_PROJECT_DIR:-$cwd}/.claude/scaffold.conf"
# shellcheck disable=SC1090
[ -f "$conf" ] && source "$conf"
[ "${SESSION_ORIENT:-on}" = "on" ] || exit 0

branch="$(git branch --show-current 2>/dev/null || true)"
[ -z "$branch" ] && exit 0

proj="${CLAUDE_PROJECT_DIR:-$cwd}"
key="$(printf '%s' "$proj" | cksum | cut -d' ' -f1)"
SNAP_DIR="${XDG_CACHE_HOME:-$HOME/.cache}/claude-scaffold"
mkdir -p "$SNAP_DIR" 2>/dev/null || true

{
  echo "Branch: $branch"
  if [ "${BEADS:-on}" = "on" ]; then
    bead="$(printf '%s' "$branch" | grep -oE "$BEAD_ID_REGEX" | head -1)"
    [ -n "$bead" ] && echo "Bead: $bead"
  fi
  dirty="$(git status --porcelain 2>/dev/null | wc -l | tr -d ' ')"
  [ "${dirty:-0}" != "0" ] && echo "Uncommitted files: $dirty"
  recent="$(git log --oneline -3 2>/dev/null || true)"
  if [ -n "$recent" ]; then echo "Recent commits:"; printf '%s\n' "$recent"; fi
} > "$SNAP_DIR/$key.snapshot" 2>/dev/null || true

exit 0
