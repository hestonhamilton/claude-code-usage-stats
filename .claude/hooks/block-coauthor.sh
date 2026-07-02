#!/usr/bin/env bash
# PreToolUse hook for Bash. Blocks AI-attribution markers in git commit messages
# and PR bodies: "Co-Authored-By:" trailers and "Generated with Claude Code"
# lines. Reads PreToolUse JSON on stdin. Honors ENFORCEMENT in
# .claude/scaffold.conf (strict denies, warn advises, off no-ops).
#
# Best-effort: it inspects the command text, so attribution passed via a file
# (git commit -F, gh pr create --body-file) is not visible here.

set -euo pipefail

ENFORCEMENT="strict"
conf="${CLAUDE_PROJECT_DIR:-.}/.claude/scaffold.conf"
# shellcheck disable=SC1090
[ -f "$conf" ] && source "$conf"

input="$(cat)"
cmd="$(printf '%s' "$input" | jq -r '.tool_input.command // ""' 2>/dev/null)"

# Only inspect commit / PR-creation commands.
if ! printf '%s' "$cmd" | grep -qE '(^|[^a-z])(git[[:space:]]+commit|gh[[:space:]]+pr[[:space:]]+(create|edit))'; then
  exit 0
fi

# Detect either attribution marker (any casing).
markers=""
printf '%s' "$cmd" | grep -qiE 'co[-_]?authored[-_]?by:' && markers="a Co-Authored-By trailer"
# Tolerate the markdown-link form: "Generated with [Claude Code](...)".
if printf '%s' "$cmd" | grep -qiE 'generated with[^a-z0-9]*claude code'; then
  markers="${markers:+$markers and }a \"Generated with Claude Code\" attribution"
fi

if [ -n "$markers" ]; then
  msg="AI-attribution is forbidden in this project's commits and PRs (found $markers). Remove it and retry."
  case "$ENFORCEMENT" in
    off)  : ;;
    warn) jq -n --arg c "ADVISORY: $msg" '{hookSpecificOutput:{hookEventName:"PreToolUse",additionalContext:$c}}' ;;
    *)    jq -n --arg reason "$msg" '{hookSpecificOutput:{hookEventName:"PreToolUse",permissionDecision:"deny",permissionDecisionReason:$reason}}' ;;
  esac
fi

exit 0
