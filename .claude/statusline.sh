#!/usr/bin/env bash
# Claude Code statusline.
# Layout: <branch>* | bead: <id> | 🤖 model <effort> | ctx: <k> (<pct>%) [⚠ /wind-down] | 5h: <Mtok> (Xh Ym left) | 7d: <Mtok>
#
# Only includes figures that are exact from local data:
#   - branch / bead / model         (direct)
#   - ctx tokens + window %         (this session's transcript; main thread only)
#   - 5h block totalTokens          (ccusage; aggregates across subagents)
#   - 5h time remaining             (clock math)
#   - 7d totalTokens (Claude-only)  (ccusage weekly)
#
# The bead id is parsed from the branch using BEAD_ID_REGEX in
# .claude/scaffold.conf, so it tracks the project's branch convention.

set -uo pipefail
input="$(cat 2>/dev/null || true)"

# --- branch + bead --------------------------------------------------------
cwd="$(printf '%s' "$input" | jq -r '.workspace.current_dir // .cwd // empty' 2>/dev/null)"
[ -z "$cwd" ] && cwd="$(pwd)"
cd "$cwd" 2>/dev/null || true

# Load bead-id pattern from project config (default covers standard bd ids).
BEAD_ID_REGEX='[a-z0-9]+-[0-9]+(\.[0-9]+)*'
conf="${CLAUDE_PROJECT_DIR:-$cwd}/.claude/scaffold.conf"
# shellcheck disable=SC1090
[ -f "$conf" ] && source "$conf"

branch="$(git branch --show-current 2>/dev/null || echo '-')"
dirty=""; [ -n "$(git status --porcelain 2>/dev/null || true)" ] && dirty="*"
bead="$(printf '%s' "$branch" | grep -oE "$BEAD_ID_REGEX" | head -1)"
[ -z "$bead" ] && bead="-"

# --- model + reasoning effort (from input) --------------------------------
model="$(printf '%s' "$input" | jq -r '.model.display_name // empty' 2>/dev/null)"
# effort.level is low|medium|high|xhigh|max; absent when the model has no effort param.
effort="$(printf '%s' "$input" | jq -r '.effort.level // empty' 2>/dev/null)"

# --- context occupancy (this session's transcript) ------------------------
# Scan the session transcript (JSONL) for the most recent usage record and sum
# its token fields. jq -R reads the file line-by-line; fromjson? skips malformed
# lines (mirrors the old per-line tolerance); awk keeps the last value seen.
CTX_WINDOW="${CTX_WINDOW:-200000}"
CTX_WINDDOWN_PCT="${CTX_WINDDOWN_PCT:-85}"
ctx_seg=""
winddown_seg=""
ctx_tokens=0
tpath="$(printf '%s' "$input" | jq -r '.transcript_path // empty' 2>/dev/null)"
if [ -n "$tpath" ] && [ -f "$tpath" ]; then
  ctx_tokens="$(jq -rR 'fromjson? | (.message.usage? // .usage?) | select(type=="object")
    | select(has("input_tokens") or has("cache_read_input_tokens"))
    | (.input_tokens//0)+(.cache_creation_input_tokens//0)+(.cache_read_input_tokens//0)' "$tpath" 2>/dev/null \
    | awk 'NF{v=$0} END{print v+0}')"
fi
[ -z "$ctx_tokens" ] && ctx_tokens=0
if [ "$ctx_tokens" -gt 0 ] 2>/dev/null; then
  ctx_k="$(awk -v t="$ctx_tokens" 'BEGIN { printf "%.0f", t/1000 }')"
  ctx_pct="$(awk -v t="$ctx_tokens" -v w="$CTX_WINDOW" 'BEGIN { printf "%.0f", (w>0 ? t*100/w : 0) }')"
  ctx_seg="ctx: ${ctx_k}k (${ctx_pct}%)"
  [ "${ctx_pct:-0}" -ge "$CTX_WINDDOWN_PCT" ] 2>/dev/null && winddown_seg="⚠ /wind-down"
fi

# --- ccusage caches -------------------------------------------------------
# The 5h/7d usage segments call `npx ccusage` (network + node). Set
# STATUSLINE_USAGE=off in .claude/scaffold.conf to drop that dependency; the
# branch/bead/model/ctx segments still work with jq + git alone.
STATUSLINE_USAGE="${STATUSLINE_USAGE:-on}"
CACHE_DIR="${XDG_CACHE_HOME:-$HOME/.cache}/claude-statusline"

fresh_or_refresh() {
  local cache="$1" ttl="$2"; shift 2
  local age=999999
  [ -f "$cache" ] && age=$(( $(date +%s) - $(stat -c %Y "$cache" 2>/dev/null || echo 0) ))
  if [ "$age" -ge "$ttl" ]; then
    timeout 12 "$@" > "$cache.tmp" 2>/dev/null && mv "$cache.tmp" "$cache" || rm -f "$cache.tmp"
  fi
}

BLOCK_CACHE="$CACHE_DIR/block.json"
WEEK_CACHE="$CACHE_DIR/week.json"
if [ "$STATUSLINE_USAGE" = "on" ] && command -v npx >/dev/null 2>&1; then
  mkdir -p "$CACHE_DIR" 2>/dev/null || true
  fresh_or_refresh "$BLOCK_CACHE" 5  npx -y --quiet ccusage blocks --json
  fresh_or_refresh "$WEEK_CACHE"  60 npx -y --quiet ccusage weekly --json
fi

# --- 5h block: raw tokens + time remaining (bash clock math) --------------
block_seg=""
if [ "$STATUSLINE_USAGE" = "on" ] && [ -s "$BLOCK_CACHE" ] && command -v jq >/dev/null 2>&1; then
  block_tokens="$(jq -r '.blocks | map(select(.isActive == true)) | first | .totalTokens // empty' "$BLOCK_CACHE" 2>/dev/null)"
  block_end="$(jq -r '.blocks | map(select(.isActive == true)) | first | .endTime // empty' "$BLOCK_CACHE" 2>/dev/null)"
  if [ -n "$block_tokens" ] && [ -n "$block_end" ]; then
    m="$(awk -v t="$block_tokens" 'BEGIN { printf "%.1f", t/1000000 }')"
    end_epoch="$(date -d "$block_end" +%s 2>/dev/null || echo 0)"
    now_epoch="$(date +%s)"
    rem=$(( end_epoch - now_epoch ))
    if [ "$rem" -gt 0 ]; then
      h=$(( rem / 3600 ))
      mn=$(( (rem % 3600) / 60 ))
      block_seg="5h: ${m}M (${h}h${mn}m left)"
    else
      block_seg="5h: ${m}M"
    fi
  fi
fi

# --- 7d tokens (Claude-only, raw) -----------------------------------------
week_seg=""
if [ "$STATUSLINE_USAGE" = "on" ] && [ -s "$WEEK_CACHE" ] && command -v jq >/dev/null 2>&1; then
  week_tokens="$(jq -r '
    .weekly[-1].modelBreakdowns
    | map(select(.modelName | startswith("claude-")))
    | map(.inputTokens + .outputTokens + .cacheCreationTokens + .cacheReadTokens) | add // 0
  ' "$WEEK_CACHE" 2>/dev/null)"
  if [ -n "$week_tokens" ] && [ "$week_tokens" != "0" ]; then
    week_m="$(awk -v t="$week_tokens" 'BEGIN { printf "%.1f", t/1000000 }')"
    week_seg="7d: ${week_m}M"
  fi
fi

# --- compose --------------------------------------------------------------
out="$(printf '\033[36m%s\033[0m%s' "$branch" "$dirty")"
[ "${BEADS:-on}" = "on" ] && out="$out$(printf '  \033[33mbead:\033[0m %s' "$bead")"
if [ -n "$model" ]; then
  out="$out  |  🤖 $model"
  [ -n "$effort" ] && out="$out $effort"
fi
if [ -n "$ctx_seg" ]; then
  ctx_color=32; [ "${ctx_pct:-0}" -ge 70 ] && ctx_color=33; [ "${ctx_pct:-0}" -ge 90 ] && ctx_color=31
  out="$out  |  \033[${ctx_color}m$ctx_seg\033[0m"
fi
[ -n "$winddown_seg" ] && out="$out  |  \033[31m$winddown_seg\033[0m"
[ -n "$block_seg" ] && out="$out  |  \033[35m$block_seg\033[0m"
[ -n "$week_seg" ]  && out="$out  |  \033[35m$week_seg\033[0m"
printf '%b' "$out"
