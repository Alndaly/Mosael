# Modal visual QA

- Source captures:
  - `/var/folders/yw/0kg9jbhj3xx00gq05_14d1lw0000gn/T/TemporaryItems/NSIRD_screencaptureui_w0mUbe/Screenshot 2026-09-01 at 19.10.58.png` (2652×1684)
  - `/var/folders/yw/0kg9jbhj3xx00gq05_14d1lw0000gn/T/TemporaryItems/NSIRD_screencaptureui_z1c8Eo/Screenshot 2026-09-01 at 19.12.21.png` (1168×1052)
- Browser-rendered implementation:
  - `/tmp/openstudio-modal-qa/command.png` (1280×720, deviceScaleFactor 1)
  - `/tmp/openstudio-modal-qa/recorder.png` (1280×720, deviceScaleFactor 1)
- Scope: global command palette translucency, shared modal surface continuity, recorder footer vertical alignment, and the shared shell used by the new-voice dialog.
- Interaction/state tested: command palette open; recorder open in idle screen mode; focused first input covered by the `ModalShell` DOM test; new-voice trigger opens a named modal with sticky footer.
- Findings and correction history:
  - The command palette's inner `Command` had an opaque `bg-popover` that covered the translucent dialog surface. It now uses a transparent inner surface over `bg-popover/90` with backdrop blur.
  - The recorder footer relied on the generic right-aligned footer. Its description and action now share a full-width `items-center justify-between` row; measured child center lines both equal 558.19 px.
  - Shared modal header, body, and footer now use the same translucent popover surface; the transparent parent prevents alpha stacking over an opaque backing layer.
- Focused region: the modal surfaces and footer were isolated because the requested changes concern only layering and alignment, not the surrounding media grid.
- Console/runtime check: production TypeScript/Vite build passed; targeted DOM tests passed.

final result: passed
