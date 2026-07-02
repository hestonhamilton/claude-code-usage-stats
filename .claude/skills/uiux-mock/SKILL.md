---
name: uiux-mock
description: Before any UI implementation, produce 2–3 self-contained HTML mockups under docs/<bead-id>-mockups/ and surface design decision points via AskUserQuestion. Forces alignment before code.
---

# uiux-mock

Autonomous through mockup generation; the decision questions are the confirmation step.

## UX priors (adjust per project)

- Keyboard-first on desktop: every primary action bindable, visible focus, no hover-only interactions.
- Mobile-first responsive: thumb-reach nav, lazy media, parity of core flows.
- Dense desktop, spacious mobile.
- No emoji in UI unless requested.

## Output layout

```
docs/<bead-id>-mockups/
  shared.css
  option-a-<slug>.html
  option-b-<slug>.html
  option-c-<slug>.html   # optional
  index.html             # side-by-side links
  README.md              # one paragraph per option + open command
```

## Mockup constraints

- Self-contained: single HTML + `shared.css`. No frameworks, no CDN. Vanilla JS only if a keyboard interaction needs demonstration.
- Placeholder media: inline SVG rects labeled with kind+dims, or a public placeholder service only when internet is available.
- Realistic data (plausible labels, counts, sizes), not lorem.
- Show empty, dense, loading, error, selected, focused states.
- Responsive at `min-width: 768px`.
- Visible keyboard-hint strip; focus rings on every focusable element; contrast ≥ 4.5:1.

## Steps

1. State the screen's purpose in one sentence and list primary actions.
2. Pick 2–3 strongly divergent approaches. Confirm bead ID + approaches with user.
3. Write `shared.css` with design tokens. Write each option file, `index.html`, `README.md`.
4. Tell the user the files exist and the open command (`xdg-open` or `python -m http.server`). **Pause** until they confirm review.
5. Ask design decision points via `AskUserQuestion`.
6. Write `docs/<bead-id>-uiux.html` (self-contained HTML) with chosen approach, rationale, keyboard map, mobile parity, components needed (S/M/L), out-of-scope. Link the chosen option file so decision + mockup sit together.
7. Leave mockup files in tree as historical artifact.

## Boundaries

- Confirm bead ID + approach concepts before writing files.
- Pause after writing files for the user to open them.
- Don't commit the decision doc until the user picks.
- Don't modify mockup files after decision is committed.
