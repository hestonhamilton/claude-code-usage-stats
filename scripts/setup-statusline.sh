#!/usr/bin/env bash
set -euo pipefail

START_MARKER="# >>> cus rate-limit capture (managed) >>>"
END_MARKER="# <<< cus rate-limit capture <<<"

usage() {
  cat <<'EOF'
Usage: setup-statusline.sh [--status-path PATH] [--apply] [--remove]

Default target: ~/.claude/statusline.sh, resolved through symlinks.
Without --apply, prints a unified diff and does not write.
EOF
}

status_path=""
apply=0
remove=0

while (($#)); do
  case "$1" in
    --status-path)
      if (($# < 2)); then
        echo "error: --status-path requires a PATH" >&2
        exit 2
      fi
      status_path="$2"
      shift 2
      ;;
    --apply)
      apply=1
      shift
      ;;
    --remove)
      remove=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "error: unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

if [[ -z "$status_path" ]]; then
  status_path="$HOME/.claude/statusline.sh"
fi

if [[ -L "$status_path" ]]; then
  resolved="$(readlink -f "$status_path")"
else
  resolved="$status_path"
fi

if [[ ! -f "$resolved" ]]; then
  echo "error: statusline file not found: $resolved" >&2
  exit 1
fi

tmp_dir="$(mktemp -d)"
trap 'rm -rf "$tmp_dir"' EXIT
block_file="$tmp_dir/block"
proposed="$tmp_dir/statusline.proposed"

cat >"$block_file" <<'EOF'
# >>> cus rate-limit capture (managed) >>>
if jq -e '.rate_limits != null' >/dev/null 2>&1 <<<"$input"; then
  cus_ratelimit_log="${CUS_RATELIMIT_LOG:-$HOME/.claude/rate-limits.jsonl}"
  mkdir -p "$(dirname "$cus_ratelimit_log")"
  jq -c --arg ts "$(date -u +%Y-%m-%dT%H:%M:%SZ)" '{
    ts: $ts,
    five_hour_pct: (.rate_limits.five_hour.used_percentage // null),
    five_hour_resets_at: (.rate_limits.five_hour.resets_at // null),
    seven_day_pct: (.rate_limits.seven_day.used_percentage // null),
    seven_day_resets_at: (.rate_limits.seven_day.resets_at // null)
  }' <<<"$input" >>"$cus_ratelimit_log"
  unset cus_ratelimit_log
fi
# <<< cus rate-limit capture <<<
EOF

marker_count="$(grep -cF "$START_MARKER" "$resolved" || true)"
end_count="$(grep -cF "$END_MARKER" "$resolved" || true)"
if [[ "$marker_count" != "$end_count" ]]; then
  echo "error: found mismatched cus managed markers in $resolved" >&2
  exit 1
fi
if ((marker_count > 1)); then
  echo "error: found multiple cus managed blocks in $resolved; remove duplicates manually first" >&2
  exit 1
fi

if ((remove)); then
  awk -v start="$START_MARKER" -v end="$END_MARKER" '
    $0 == start { in_block = 1; next }
    $0 == end { in_block = 0; next }
    !in_block { print }
  ' "$resolved" >"$proposed"
elif ((marker_count == 1)); then
  awk -v start="$START_MARKER" -v end="$END_MARKER" -v block_file="$block_file" '
    BEGIN {
      while ((getline line < block_file) > 0) {
        block = block line ORS
      }
      close(block_file)
    }
    $0 == start {
      printf "%s", block
      in_block = 1
      next
    }
    $0 == end {
      in_block = 0
      next
    }
    !in_block { print }
  ' "$resolved" >"$proposed"
else
  if ! grep -q '^[[:space:]]*input="$(cat)"[[:space:]]*$' "$resolved"; then
    cat >&2 <<EOF
error: could not find the statusline stdin anchor in $resolved:

  input="\$(cat)"

Add that line near the top of your Claude Code statusline script so stdin is
captured once, then re-run this patcher. The managed cus block belongs
immediately after that anchor.
EOF
    exit 1
  fi
  awk -v block_file="$block_file" '
    BEGIN {
      while ((getline line < block_file) > 0) {
        block = block line ORS
      }
      close(block_file)
    }
    /^[[:space:]]*input="\$\(cat\)"[[:space:]]*$/ && !inserted {
      print
      printf "%s", block
      inserted = 1
      next
    }
    { print }
  ' "$resolved" >"$proposed"
fi

if ((apply == 0)); then
  diff -u "$resolved" "$proposed" || true
  echo "dry run only: re-run with --apply to write changes."
  exit 0
fi

if cmp -s "$resolved" "$proposed"; then
  echo "no changes needed: $resolved"
  echo "reminder: this target is likely a version-controlled dotfile; commit and sync it to the other machines."
  exit 0
fi

backup="$resolved.bak.$(date +%s)"
cp -p "$resolved" "$backup"
cp "$proposed" "$resolved"
chmod --reference="$backup" "$resolved" 2>/dev/null || true
echo "updated: $resolved"
echo "backup: $backup"
echo "reminder: this target is likely a version-controlled dotfile; commit and sync it to the other machines."
