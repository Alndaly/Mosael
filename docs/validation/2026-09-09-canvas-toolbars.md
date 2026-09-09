# Canvas toolbars and workflow node panels — 2026-09-09

## Changes

Boards and workflows share one toolbar surface, with divider-separated editing, comment, marker, view and assistant groups. Workflow readiness, run history and Run are adjacent. Revision history, export and deletion live under More; deletion retains its confirmation dialog. Subgraph editing follows the same edit/view order.

Narrow toolbars show explicit previous/next controls. Assistant, workflow run controls and More remain outside the scrolling area. Titles truncate without wrapping; docked assistants still begin one standard gap below the 42 px toolbar.

Workflow node tools use the board's compact rounded action bar. The inspector uses the same modal surface as board composers, a 460 px responsive width, compact header and independently scrolling form. Field wrapper selectors now target direct inputs only: nested MapField name inputs were forced to 40 px while value selectors stayed at 32 px; both now measure 32 px.

## Verification

- Frontend: 63 relevant test files / 360 tests passed (workflows, boards, markers, app components, UI and design).
- TypeScript and frontend production build passed. Website production build passed with the updated English and Chinese guides.
- Oxlint on changed components passed. `git diff --check` passed.
- Chromium against the isolated demo backend: both pages in light/dark themes, at 1440, 1100, 900 and 768 px widths.
- Verified mutually exclusive comment/marker modes, Escape, independent annotation visibility, retained edges, More → Delete → Cancel, inspector section switching, rename followed by undo while in marker mode, and assistant opening/closing without submitting a prompt.
- Verified toolbar/title non-overlap, constant height, visible pinned actions, arrows reaching both ends and disappearing when the window widens.
- Browser checks produced no page errors. Evidence: `output/playwright/canvas-toolbar-verification.json`, `*-toolbar-{light,dark}-{1440,1100,900,768}.png` and `*-toolbar-{light,dark}-assistant.png` (local, ignored).

Backend execution, model generation and release packaging are unchanged and were not rerun for this UI change.
