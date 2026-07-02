#!/usr/bin/env bash
# PostToolUse hook for Edit|Write. If an edited source file matches one of the
# configured extensions and the project's lint binary is available, run the
# lint-fix command on that file and surface diagnostics back to the assistant.
#
# Lint command + extensions are read from .claude/scaffold.conf.

set -euo pipefail

# Load project config (defaults if missing).
LINT_CMD="ruff check --fix"
LINT_EXTS="py"
conf="${CLAUDE_PROJECT_DIR:-.}/.claude/scaffold.conf"
# shellcheck disable=SC1090
[ -f "$conf" ] && source "$conf"

input="$(cat)"
file_path="$(printf '%s' "$input" | jq -r '.tool_input.file_path // .tool_input.notebook_path // ""' 2>/dev/null)"

[ -z "$file_path" ] && exit 0

# Bail if the extension isn't configured.
ext="${file_path##*.}"
matched=0
for e in $LINT_EXTS; do
  [ "$ext" = "$e" ] && { matched=1; break; }
done
[ "$matched" -eq 1 ] || exit 0

# Split the lint command into binary + args.
lint_bin="${LINT_CMD%% *}"
lint_args=""
[ "$LINT_CMD" != "$lint_bin" ] && lint_args="${LINT_CMD#"$lint_bin" }"

# Locate the nearest project root (walk up until pyproject.toml/package.json/.git).
root="$(dirname "$file_path")"
while [ "$root" != "/" ] && [ ! -e "$root/.git" ] && [ ! -e "$root/pyproject.toml" ] && [ ! -e "$root/package.json" ]; do
  root="$(dirname "$root")"
done

# Also find the workspace/git top level. In a monorepo the nearest package.json
# is often a leaf package whose node_modules/.bin lacks the tool; the hoisted
# binary lives at the workspace root. Resolve that too and prefer it.
gitroot="$(git -C "$root" rev-parse --show-toplevel 2>/dev/null || true)"

# Prefer a project-local venv copy of the binary, then the workspace-root
# node_modules, then the nearest node_modules; fall back to PATH.
resolved=""
if [ -x "$root/.venv/bin/$lint_bin" ]; then
  resolved="$root/.venv/bin/$lint_bin"
elif [ -x "$root/.test.venv/bin/$lint_bin" ]; then
  resolved="$root/.test.venv/bin/$lint_bin"
elif [ -n "$gitroot" ] && [ -x "$gitroot/node_modules/.bin/$lint_bin" ]; then
  resolved="$gitroot/node_modules/.bin/$lint_bin"
elif [ -x "$root/node_modules/.bin/$lint_bin" ]; then
  resolved="$root/node_modules/.bin/$lint_bin"
elif command -v "$lint_bin" >/dev/null 2>&1; then
  resolved="$lint_bin"
fi

[ -z "$resolved" ] && exit 0

# Run lint --fix; never block a write.
# shellcheck disable=SC2086
out="$("$resolved" $lint_args "$file_path" 2>&1 || true)"

if [ -n "$out" ] && ! printf '%s' "$out" | grep -qE 'All checks passed|^$'; then
  jq -n --arg msg "lint ($lint_bin) on $file_path:
$out" '{
    hookSpecificOutput: {
      hookEventName: "PostToolUse",
      additionalContext: $msg
    }
  }' 2>/dev/null || cat <<EOF
{"hookSpecificOutput":{"hookEventName":"PostToolUse","additionalContext":"lint ran on $file_path; see diagnostics in the file."}}
EOF
fi

exit 0
