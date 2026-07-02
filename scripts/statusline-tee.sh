#!/usr/bin/env bash
# Snippet for capturing Claude Code statusline rate-limit JSON.
#
# Paste this into the top of your existing claude-statusline.sh. The important
# wiring is:
#
#   input="$(cat)"
#   cus_capture_rate_limits "$input"
#   printf '%s\n' "$input" | your_existing_statusline_renderer
#
# If your existing script currently reads stdin itself, replace that read with
# the captured $input value so stdin is consumed exactly once.

cus_capture_rate_limits() {
  local input="$1"
  local log_path="${CUS_RATELIMIT_LOG:-$HOME/.claude/rate-limits.jsonl}"
  local log_dir
  log_dir="$(dirname "$log_path")"

  if ! jq -e '.rate_limits != null' >/dev/null 2>&1 <<<"$input"; then
    return 0
  fi

  mkdir -p "$log_dir"
  jq -c --arg ts "$(date -u +%Y-%m-%dT%H:%M:%SZ)" '{
    ts: $ts,
    five_hour_pct: (.rate_limits.five_hour.used_percentage // null),
    five_hour_resets_at: (.rate_limits.five_hour.resets_at // null),
    seven_day_pct: (.rate_limits.seven_day.used_percentage // null),
    seven_day_resets_at: (.rate_limits.seven_day.resets_at // null)
  }' <<<"$input" >>"$log_path"
}
