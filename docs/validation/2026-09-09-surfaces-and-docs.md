# Softer surfaces and documentation navigation — 2026-09-09

## Changes

- Decorative border tokens are quieter in light, dark and custom-background appearances. Node actions, floating tooltips, menus, dialogs, notifications and colored notes use the shared surface hierarchy. Functional focus, selection, graph connections and transform handles remain distinct.
- Documentation uses six task-based groups. The 22 pages in each language retain their URLs, and previous/next links follow the same navigation order.
- Mobile/tablet documentation uses one compact navigation bar and one Radix dialog at a time. The dialog scrolls internally, closes on Escape, backdrop clicks and link navigation, restores focus, and closes when switching to the desktop layout. Heading offsets account for both navigation bars.
- Both READMEs and all 44 localized document titles/descriptions were reviewed and updated. Introductory flows, board/document/workflow explanations, website metadata and maintainer guidance were rewritten. Corrected provider settings paths, credential storage on remote backends, local plugin permissions, Chrome extension support and obsolete publishing instructions. Historical release notes remain historical.

## Validation

- Frontend: 40 relevant test files, 202 tests passed (design, boards, markers, shared UI).
- Frontend TypeScript and production build passed. The existing large-bundle advisory remains.
- Website: 10 tests passed, including complete navigation membership, reading order, localized links and media provenance.
- Backend documentation consistency: 4 tests passed.
- Website production build passed (71 static pages).
- Browser navigation checks: 16 combinations (en/zh × light/dark × 390/768/1100/1440 px). Verified no horizontal overflow, compact first-screen heading, all document links, current-page state, scene navigation, TOC anchors, Escape, backdrop dismissal, focus restoration and desktop resize cleanup. No page errors.
- Actual board screenshots verified the selected video node's top actions and bottom composer in light and dark themes using isolated demo data. No model generation or personal workspace changes.
- `git diff --check` passed.

Website ESLint remains blocked before analyzing code: the installed typescript-eslint 8.69.0 rejects TypeScript 7.0.2. This is the existing dependency incompatibility documented in website/README.md; builds and type checks ran successfully.

## Reproduce

Start the built website on port 3002, then run:

```sh
backend/.venv/bin/python scripts/verify-docs-navigation.py
```

Screenshots and the machine-readable matrix are written to `output/playwright/`. They include `docs-{locale}-{theme}-{width}.png` and `docs-menu-{locale}-{theme}-{width}.png`. Local board checks are saved as `board-soft-boundaries-{theme}.png` in the same folder. These are validation captures, not replacements for historical 1.2.0 recordings.
