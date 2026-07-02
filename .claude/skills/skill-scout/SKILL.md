---
name: skill-scout
description: Summarize recent transcripts looking for noise — failed tool calls, repeated tool calls, repetitive ad-hoc sequences — and surface candidate skill ideas. Use occasionally when sessions feel friction-heavy.
---

# skill-scout

Lightweight. Read-only scan, then a short report. No file creation without confirmation.

## Inputs

- Optional `--since <duration>` (default `7d`).

## Steps

1. Find this project's transcripts under `~/.claude/projects/<encoded-project-path>/*.jsonl` modified within the window.
2. For each, count:
   - **Failed tool calls** — `tool_result` with `is_error: true` or stderr containing `Error|denied|failed`.
   - **Repeated tool calls** — same `tool_use.name` + first arg ≥3 times in a row.
   - **Long Bash chains without a Skill invocation** — ≥6 consecutive Bash uses with no Skill between.
3. Produce a short markdown report (inline) with:
   - Top failure modes (tool + error pattern + count).
   - Top repetition patterns (tool + arg shape + count).
   - 0–3 candidate skill ideas, one line each: name guess, the recurring pattern, why a skill might help.
4. Ask the user which (if any) to act on. Only then create or amend a SKILL.md.

## Boundaries

- Never create/edit/delete SKILL.md files without explicit approval.
- Keep the report short — bullet lists, not prose.
