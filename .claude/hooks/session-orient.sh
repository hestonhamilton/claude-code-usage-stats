#!/usr/bin/env bash
# SessionStart hook. On a genuine cold start (source=startup) inject a compact
# orientation block; on source=compact re-inject only the snapshot the PreCompact
# hook saved (so in-progress state survives compaction). Subagent-safe, cheap,
# read-only, and gated by SESSION_ORIENT in .claude/scaffold.conf.
set -uo pipefail

input="$(cat 2>/dev/null || true)"

# Never orient inside a subagent (agent_id is present only there) — avoids
# double-prompting fan-out agents with the main thread's context.
agent_id="$(printf '%s' "$input" | jq -r '.agent_id // empty' 2>/dev/null)"
[ -n "$agent_id" ] && exit 0

# Only act on a true cold start or right after compaction.
src="$(printf '%s' "$input" | jq -r '.source // empty' 2>/dev/null)"
case "$src" in startup|compact) ;; *) exit 0 ;; esac

cwd="$(printf '%s' "$input" | jq -r '.cwd // .workspace.current_dir // empty' 2>/dev/null)"
[ -n "$cwd" ] && cd "$cwd" 2>/dev/null || true

SESSION_ORIENT="on"; BEADS="on"; BEAD_ID_REGEX='[a-z0-9]+-[0-9]+(\.[0-9]+)*'
conf="${CLAUDE_PROJECT_DIR:-$cwd}/.claude/scaffold.conf"
# shellcheck disable=SC1090
[ -f "$conf" ] && source "$conf"
[ "${SESSION_ORIENT:-on}" = "on" ] || exit 0

emit() { # emit BODY  (empty body => stay silent)
  [ -z "$1" ] && exit 0
  jq -n --arg c "$1" '{hookSpecificOutput:{hookEventName:"SessionStart",additionalContext:$c}}'
  exit 0
}

proj="${CLAUDE_PROJECT_DIR:-$cwd}"
key="$(printf '%s' "$proj" | cksum | cut -d' ' -f1)"
SNAP="${XDG_CACHE_HOME:-$HOME/.cache}/claude-scaffold/$key.snapshot"

# After compaction: re-inject the saved snapshot only (minimal, focused).
if [ "$src" = "compact" ]; then
  [ -f "$SNAP" ] || exit 0
  emit "State recovered after compaction (scaffold):
$(cat "$SNAP" 2>/dev/null)

Resume from here; re-read the active phase artifact if you need detail."
fi

# Cold start (source=startup): build a compact orientation block.
branch="$(git branch --show-current 2>/dev/null || true)"
[ -z "$branch" ] && exit 0  # not a git work tree / detached — nothing useful to say
out="On branch: $branch"
dirty="$(git status --porcelain 2>/dev/null | wc -l | tr -d ' ')"
[ "${dirty:-0}" != "0" ] && out="$out ($dirty uncommitted file(s))"
if [ "${BEADS:-on}" = "on" ]; then
  bead="$(printf '%s' "$branch" | grep -oE "$BEAD_ID_REGEX" | head -1)"
  [ -n "$bead" ] && out="$out"$'\n'"Active bead: $bead"
  if command -v bd >/dev/null 2>&1; then
    ready="$(timeout 5 bd ready 2>/dev/null | head -4)"
    [ -n "$ready" ] && out="$out"$'\n'"bd ready (top):"$'\n'"$ready"
  fi
fi
hf="${CLAUDE_PROJECT_DIR:-$cwd}/HANDOFF.md"
if [ -f "$hf" ]; then
  prio="$(awk '/^## Next Session Priority/{f=1;next} /^## /{f=0} f' "$hf" | sed '/^[[:space:]]*$/d' | head -4)"
  [ -n "$prio" ] && out="$out"$'\n'"Next priority (HANDOFF.md):"$'\n'"$prio"
fi
emit "Session orientation (scaffold):
$out

Resume with /flow, or /bead-start to claim the next bead."
