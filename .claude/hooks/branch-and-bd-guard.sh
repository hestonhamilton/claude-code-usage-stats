#!/usr/bin/env bash
# PreToolUse hook for Bash.
# - DENIES `git switch -c <name>` / `git checkout -b <name>` when <name>
#   doesn't match <BRANCH_PREFIX><bead-id>-<slug>. The statusline + skills
#   derive bead context from the branch, so this has real functional impact.
# - DENIES `git worktree add` when WORKTREE_GUARD=bd — steers to
#   `bd worktree create`, which wires the worktree into .gitignore and the
#   shared beads DB.
#
# Convention values are read from .claude/scaffold.conf.

set -euo pipefail

# Load project config (defaults if missing).
ENFORCEMENT="strict"
BEADS="on"
BRANCH_PREFIX="feat/"
BEAD_ID_REGEX='[a-z0-9]+-[0-9]+(\.[0-9]+)*'
BRANCH_GRANDFATHER=""
WORKTREE_GUARD="bd"
conf="${CLAUDE_PROJECT_DIR:-.}/.claude/scaffold.conf"
# shellcheck disable=SC1090
[ -f "$conf" ] && source "$conf"

input="$(cat)"
cmd="$(printf '%s' "$input" | jq -r '.tool_input.command // ""' 2>/dev/null)"

# Respect the adoption mode: strict denies, warn advises (but allows), off no-ops.
respond() {
  case "$ENFORCEMENT" in
    off)  exit 0 ;;
    warn) jq -n --arg c "ADVISORY: $1" '{hookSpecificOutput:{hookEventName:"PreToolUse",additionalContext:$c}}'; exit 0 ;;
    *)    jq -n --arg reason "$1" '{hookSpecificOutput:{hookEventName:"PreToolUse",permissionDecision:"deny",permissionDecisionReason:$reason}}'; exit 0 ;;
  esac
}

# --- git branch creation: deny off-convention names ------------------------
new_branch=""
if printf '%s' "$cmd" | grep -qE '(^|[^a-z])git[[:space:]]+switch[[:space:]]+(-[^c[:space:]]*c|--create)[[:space:]]'; then
  new_branch="$(printf '%s' "$cmd" | sed -nE 's/.*git[[:space:]]+switch[[:space:]]+(-[^[:space:]]*|--create)[[:space:]]+([^[:space:]]+).*/\2/p' | head -1)"
elif printf '%s' "$cmd" | grep -qE '(^|[^a-z])git[[:space:]]+checkout[[:space:]]+(-[^b[:space:]]*b|--branch)[[:space:]]'; then
  new_branch="$(printf '%s' "$cmd" | sed -nE 's/.*git[[:space:]]+checkout[[:space:]]+(-[^[:space:]]*|--branch)[[:space:]]+([^[:space:]]+).*/\2/p' | head -1)"
fi

if [ -n "$new_branch" ]; then
  ok=0
  # Always allow base branches.
  printf '%s' "$new_branch" | grep -qE '^(main|master|develop)$' && ok=1
  # Allow the configured convention. With BEADS=on the slug must start with a
  # bead id; with BEADS=off, just <prefix><kebab-slug>.
  if [ "${BEADS:-on}" = "on" ]; then
    conv="^${BRANCH_PREFIX}${BEAD_ID_REGEX}-[a-z0-9][a-z0-9-]*$"
    want="${BRANCH_PREFIX}<bead-id>-<kebab-slug> (bead-id pattern: ${BEAD_ID_REGEX})"
  else
    conv="^${BRANCH_PREFIX}[a-z0-9][a-z0-9-]*$"
    want="${BRANCH_PREFIX}<kebab-slug>"
  fi
  printf '%s' "$new_branch" | grep -qE "$conv" && ok=1
  # Allow grandfathered branches.
  if [ -n "$BRANCH_GRANDFATHER" ]; then
    printf '%s' "$new_branch" | grep -qE "^(${BRANCH_GRANDFATHER})$" && ok=1
  fi
  if [ "$ok" -ne 1 ]; then
    respond "Branch name \"${new_branch}\" does not match ${want}. The statusline and skills derive context from this pattern. Adjust the name, or grandfather it via BRANCH_GRANDFATHER in .claude/scaffold.conf."
  fi
fi

# --- git worktree add: steer to bd worktree create (beads repos only) ------
if [ "${BEADS:-on}" = "on" ] && [ "$WORKTREE_GUARD" = "bd" ] && printf '%s' "$cmd" | grep -qE '(^|[^a-z])git[[:space:]]+worktree[[:space:]]+add([[:space:]]|$)'; then
  respond "Use 'bd worktree create <name> --branch ${BRANCH_PREFIX}<bead-id>-<slug>' instead of 'git worktree add'. The bd command adds the worktree to .gitignore and wires it into the shared beads DB; plain git worktree add skips that setup. (Set WORKTREE_GUARD=off in .claude/scaffold.conf to disable.)"
fi

exit 0
