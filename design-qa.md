# OpenStudio design QA log

## Modal visual QA

- Source captures:
  - `/var/folders/yw/0kg9jbhj3xx00gq05_14d1lw0000gn/T/TemporaryItems/NSIRD_screencaptureui_w0mUbe/Screenshot 2026-09-01 at 19.10.58.png` (2652×1684)
  - `/var/folders/yw/0kg9jbhj3xx00gq05_14d1lw0000gn/T/TemporaryItems/NSIRD_screencaptureui_z1c8Eo/Screenshot 2026-09-01 at 19.12.21.png` (1168×1052)
  - `/var/folders/yw/0kg9jbhj3xx00gq05_14d1lw0000gn/T/TemporaryItems/NSIRD_screencaptureui_yYJ2jA/Screenshot 2026-09-01 at 19.20.00.png` (986×586)
  - `/var/folders/yw/0kg9jbhj3xx00gq05_14d1lw0000gn/T/TemporaryItems/NSIRD_screencaptureui_8pXLc7/Screenshot 2026-09-01 at 19.26.25.png` (986×1514)
  - `/var/folders/yw/0kg9jbhj3xx00gq05_14d1lw0000gn/T/TemporaryItems/NSIRD_screencaptureui_FwaIB0/Screenshot 2026-09-01 at 19.32.14.png` (936×1412)
  - `/var/folders/yw/0kg9jbhj3xx00gq05_14d1lw0000gn/T/TemporaryItems/NSIRD_screencaptureui_iUjAHB/Screenshot 2026-09-01 at 19.35.40.png` (1108×1546)
  - `/var/folders/yw/0kg9jbhj3xx00gq05_14d1lw0000gn/T/TemporaryItems/NSIRD_screencaptureui_Qxi1LN/Screenshot 2026-09-01 at 19.36.43.png` (992×1434)
  - `/var/folders/yw/0kg9jbhj3xx00gq05_14d1lw0000gn/T/TemporaryItems/NSIRD_screencaptureui_aQJTEQ/Screenshot 2026-09-01 at 18.55.53.png` (3456×2234)
- Browser-rendered implementation:
  - `/tmp/openstudio-modal-qa/command.png` (1280×720, deviceScaleFactor 1)
  - `/tmp/openstudio-modal-qa/recorder.png` (1280×720, deviceScaleFactor 1)
  - `output/playwright/editor-upload-voice-dialog.png`
  - `output/playwright/editor-from-speaker-dialog.png`
  - `output/playwright/editor-voice-empty-state-full.png`
  - `output/playwright/editor-remote-engine-no-voice-library.png`
  - `output/playwright/provider-edit-endpoint-without-initial-model.png`
- Scope: global command palette translucency, shared modal surface continuity, recorder footer vertical alignment, voice-creation forms moved from settings/editor inline regions into the shared modal system, and engine-scoped visibility of the editor voice library.
- Interaction/state tested: command palette open; recorder open in idle screen mode; focused first input covered by the `ModalShell` DOM test; settings new-voice, editor upload/record, and editor from-speaker triggers open named modals with sticky footers; switching from local clone to Edge removes the entire local voice-library region.
- Findings and correction history:
  - The command palette's inner `Command` had an opaque `bg-popover` that covered the translucent dialog surface. It now uses a transparent inner surface over `bg-popover/90` with backdrop blur.
  - The recorder footer relied on the generic right-aligned footer. Its description and action now share a full-width `items-center justify-between` row; measured child center lines both equal 558.19 px.
  - Shared modal header, body, and footer now use the same translucent popover surface; the transparent parent prevents alpha stacking over an opaque backing layer.
  - Settings and editor now share one upload/record voice dialog. The editor's from-speaker flow uses a separate modal because its asset/transcript context is project-bound; neither form changes the height of the voice list anymore.
  - The empty clone selector is a short disabled control; the voice-library empty state fills the panel without a decorative container or icon tile. Both disappear with the library when a remote TTS engine is selected.
  - Provider editing now shows `百炼 API Endpoint` with protocol-specific help and omits the create-only initial-model field; the browser snapshot verifies the AI Video entry point rather than only the chat settings page.
- Focused region: the modal surfaces and footer were isolated because the requested changes concern only layering and alignment, not the surrounding media grid.
- Console/runtime check: production TypeScript/Vite build passed; targeted DOM tests passed.

final result: passed

---

## Transcript row design QA

### Comparison target

- Source visual truth: `/var/folders/yw/0kg9jbhj3xx00gq05_14d1lw0000gn/T/TemporaryItems/NSIRD_screencaptureui_C8rYpV/Screenshot 2026-09-01 at 23.57.43.png`
- Browser-rendered implementation: the authenticated editor is an Electron-only state; the in-app browser reached the unauthenticated login screen and was not used as visual evidence.
- Implementation screenshot: `/var/folders/yw/0kg9jbhj3xx00gq05_14d1lw0000gn/T/com.openai.sky.CUAService/Open Studio Screenshot 2026-09-01 at 11.59.57 PM.jpeg`
- Focused implementation crop: `/tmp/openstudio-design-qa/transcript-row-implementation.png`
- Combined source/implementation comparison: `/tmp/openstudio-design-qa/transcript-row-comparison.png`
- State: dark theme, editor transcript panel, multiple detected speakers, long sentence wrapping to a second line, row actions at rest.

### Viewport and normalization

- Source pixels: `678 × 170`.
- Full Electron implementation capture: `1225 × 768` pixels.
- Focused implementation source crop: `235 × 55` pixels from the full capture.
- Comparison normalization: the focused implementation crop was Lanczos-scaled to `678 × 170`; both images were then stacked at equal pixel dimensions.
- The Computer Use capture does not expose Electron's CSS viewport or device pixel ratio. The comparison therefore uses equal normalized output pixels rather than claiming unverified CSS-density parity.

### Findings

No actionable P0/P1/P2 findings remain in the requested transcript row.

- Fonts and typography: the body retains the existing product font and size. Body, timestamp, and speaker metadata now share a `24px` first-line rhythm. Long text remains complete and wraps naturally; no truncation class is applied.
- Spacing and layout rhythm: timestamp and speaker are one compact top-aligned metadata group. The previous vertical speaker stack and permanent `22px`/`40px` action padding are removed.
- Colors and visual tokens: existing primary, muted, panel, border, and speaker-color tokens are preserved.
- Image quality and asset fidelity: this row contains no raster assets. Existing Lucide action icons are retained rather than replaced.
- Copy and content: transcript words, timestamps, speaker IDs, labels, and tooltips are unchanged.
- Interaction states: word seek, drag selection, double-click marking, active-word highlighting, sentence split, and sentence cut handlers are preserved. DOM tests verify that the action rail is absolutely positioned and consumes no resting layout width. A post-fix hover screenshot could not be captured because the Electron Computer Use window stopped accepting pointer actions; this is a residual P3 visual-evidence gap, not a known functional issue.

### Full-view comparison evidence

The full Electron capture shows the transcript panel in its actual authenticated editor context. Rows are materially denser than the source complaint, timestamp and speaker IDs sit on the same first line as the body, and long copy continues on the next line without clipping.

### Focused-region comparison evidence

The combined comparison at `/tmp/openstudio-design-qa/transcript-row-comparison.png` places the user's reported row above the revised rendered row. The revised row removes the oversized body line box, aligns left metadata to the first text line, and hides the action rail in the resting state.

### Comparison history

1. Initial implementation moved the speaker from below the timestamp into a separate grid column. The user's follow-up exposed three P2 issues: excess metadata width, vertically centered speaker metadata on wrapped rows, and permanently reserved action space.
2. The metadata was consolidated into one compact group and the actions moved to an absolute hover rail. The user's next capture exposed a remaining P2 line-height mismatch: the body used `1.9` line-height while smaller metadata used a different visual line box; body focus also kept row actions visible.
3. The body and metadata were normalized to a `24px` first-line rhythm, the metadata group was vertically centered within that same line box, and action visibility was restricted to row hover or focus inside the action rail itself. The post-fix Electron capture and focused comparison show no remaining P0/P1/P2 mismatch.

### Verification

- `pnpm --dir frontend exec vitest run src/features/editor/TranscriptPanel.dom.test.tsx` — 5 tests passed.
- `pnpm --dir frontend build` — passed.
- Focused DOM coverage verifies horizontal metadata grouping, natural wrapping, and zero resting action reservation.

### Follow-up polish

- P3: capture the final hover rail visually when Electron pointer capture is available again; current structure and interaction handlers are covered by DOM tests.

final result: passed
