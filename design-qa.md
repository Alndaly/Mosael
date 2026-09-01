# Modal visual QA

- Source captures:
  - `/var/folders/yw/0kg9jbhj3xx00gq05_14d1lw0000gn/T/TemporaryItems/NSIRD_screencaptureui_w0mUbe/Screenshot 2026-09-01 at 19.10.58.png` (2652×1684)
  - `/var/folders/yw/0kg9jbhj3xx00gq05_14d1lw0000gn/T/TemporaryItems/NSIRD_screencaptureui_z1c8Eo/Screenshot 2026-09-01 at 19.12.21.png` (1168×1052)
  - `/var/folders/yw/0kg9jbhj3xx00gq05_14d1lw0000gn/T/TemporaryItems/NSIRD_screencaptureui_yYJ2jA/Screenshot 2026-09-01 at 19.20.00.png` (986×586)
  - `/var/folders/yw/0kg9jbhj3xx00gq05_14d1lw0000gn/T/TemporaryItems/NSIRD_screencaptureui_8pXLc7/Screenshot 2026-09-01 at 19.26.25.png` (986×1514)
  - `/var/folders/yw/0kg9jbhj3xx00gq05_14d1lw0000gn/T/TemporaryItems/NSIRD_screencaptureui_FwaIB0/Screenshot 2026-09-01 at 19.32.14.png` (936×1412)
  - `/var/folders/yw/0kg9jbhj3xx00gq05_14d1lw0000gn/T/TemporaryItems/NSIRD_screencaptureui_iUjAHB/Screenshot 2026-09-01 at 19.35.40.png` (1108×1546)
  - `/var/folders/yw/0kg9jbhj3xx00gq05_14d1lw0000gn/T/TemporaryItems/NSIRD_screencaptureui_Qxi1LN/Screenshot 2026-09-01 at 19.36.43.png` (992×1434)
- Browser-rendered implementation:
  - `/tmp/openstudio-modal-qa/command.png` (1280×720, deviceScaleFactor 1)
  - `/tmp/openstudio-modal-qa/recorder.png` (1280×720, deviceScaleFactor 1)
  - `output/playwright/editor-upload-voice-dialog.png`
  - `output/playwright/editor-from-speaker-dialog.png`
  - `output/playwright/editor-voice-empty-state-full.png`
  - `output/playwright/editor-remote-engine-no-voice-library.png`
- Scope: global command palette translucency, shared modal surface continuity, recorder footer vertical alignment, voice-creation forms moved from settings/editor inline regions into the shared modal system, and engine-scoped visibility of the editor voice library.
- Interaction/state tested: command palette open; recorder open in idle screen mode; focused first input covered by the `ModalShell` DOM test; settings new-voice, editor upload/record, and editor from-speaker triggers open named modals with sticky footers; switching from local clone to Edge removes the entire local voice-library region.
- Findings and correction history:
  - The command palette's inner `Command` had an opaque `bg-popover` that covered the translucent dialog surface. It now uses a transparent inner surface over `bg-popover/90` with backdrop blur.
  - The recorder footer relied on the generic right-aligned footer. Its description and action now share a full-width `items-center justify-between` row; measured child center lines both equal 558.19 px.
  - Shared modal header, body, and footer now use the same translucent popover surface; the transparent parent prevents alpha stacking over an opaque backing layer.
  - Settings and editor now share one upload/record voice dialog. The editor's from-speaker flow uses a separate modal because its asset/transcript context is project-bound; neither form changes the height of the voice list anymore.
  - The empty clone selector is a short disabled control; the voice-library empty state fills the panel without a decorative container or icon tile. Both disappear with the library when a remote TTS engine is selected.
- Focused region: the modal surfaces and footer were isolated because the requested changes concern only layering and alignment, not the surrounding media grid.
- Console/runtime check: production TypeScript/Vite build passed; targeted DOM tests passed.

final result: passed
