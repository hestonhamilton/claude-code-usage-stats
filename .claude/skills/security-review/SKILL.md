---
name: security-review
description: Audit a diff against the project's threat surface. A general checklist by default; refine the specifics for the project's concrete frameworks/storage as they're chosen.
---

# security-review

Audit-only. Produce a findings report; never modify code.

## Recurring threat themes (refine for this project's stack)

1. **Input from untrusted sources** — SSRF (internal hosts, file://), path traversal, injection (SQL/shell/template), header/cookie injection.
2. **Auth + session** — every route has a role check; session cookies `HttpOnly + Secure + SameSite`; CSRF on state-changing routes.
3. **File / upload safety** — sniff MIME, reject executables/auto-extracting archives, size-cap before hashing, never serve user content from an executable path.
4. **Token / credential scope** — least privilege, immediate revocation, audit log on mutations.
5. **Secrets in git** — `.env`, keys, cookie jars must be gitignored and absent from `git ls-files`.
6. **Abuse + rate** — rate limits on expensive endpoints, login backoff, concurrency caps.

(Add framework-specific checks here as the stack solidifies.)

## Steps

1. `git diff --name-only <base>...HEAD` — identify touched files.
2. Map files to the themes above; skip untouched themes.
3. For each touched theme: read changed code, look for the pattern + its negation, note file:line.
4. Tool sweep when relevant (e.g. `ruff check --select S`, `npm audit`, `bandit`) if available.
5. Output a report:
   - **Per theme:** pass / risk / fail (one sentence).
   - **Findings:** `SR-<n>` with file:line, severity, description, mitigation.
   - **Out of scope:** themes the diff didn't touch.
   Inline is fine for a quick sweep. When persisting, write `docs/<bead-id>-security-review.html` (self-contained HTML, copied from `docs/_doc-template.html`): per-theme verdicts as a pass/risk/fail matrix; each `SR-<n>` as a finding block with a severity badge.
6. For any high finding: propose a bead before merge. Confirm before `bd create`.

## Boundaries

- This skill audits; fixes go through normal bead workflow.
- Confirm before creating any bead from findings.
