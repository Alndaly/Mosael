# Mosael design QA log

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
  - `/tmp/mosael-modal-qa/command.png` (1280×720, deviceScaleFactor 1)
  - `/tmp/mosael-modal-qa/recorder.png` (1280×720, deviceScaleFactor 1)
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

## Desktop status icon

### Visual truth and implementation evidence

- Source visual truth: `/Users/kinda/Desktop/Codex Image Sep 2, 2026, 04_30_52 PM.png` (`1536 × 1024`, transparent RGBA; visible-mark bounds `988 × 526`).
- Preserved source asset: `brand/mosael-tray-mark.png`.
- Rendered implementation comparison: `docs/media/design-qa/mosael-tray/tray-comparison.png` (`960 × 240`).
- State: supplied Mosael mark beside the generated Windows light-taskbar and dark-taskbar resources. The same alpha silhouette drives the macOS template resource.
- Density normalization: the source mark is shown at `280 × 149`; the `32 × 32` 2× tray outputs are enlarged with nearest-neighbor sampling so their actual pixel decisions remain visible rather than being smoothed by the QA sheet.

### Findings

No actionable P0, P1, or P2 findings remain.

- Fonts and typography: not applicable; the persistent status item is icon-only and introduces no text.
- Spacing and layout rhythm: macOS uses an `18 × 18` logical canvas with a `36 × 36` Retina representation. Windows uses `16 × 16` plus `32 × 32` 2× resources. The wide mark is optically centered with transparent breathing room and no background tile or shadow.
- Colors and visual tokens: macOS receives a template image so the OS owns menu-bar contrast. Windows receives the same silhouette in black for light taskbars and white for dark taskbars, switching with `nativeTheme`.
- Image quality and asset fidelity: all six runtime resources are rasterized directly from the supplied transparent PNG. The wave, crossing cut, lower curve, and detached dot remain recognizable at native status-icon size; no SVG, CSS drawing, or substitute glyph was introduced.
- Copy and content: not applicable; tray tooltip and menu copy remain unchanged.

### Comparison history

1. The previous tray template used an unrelated node/graph glyph, while Windows reused the square application icon (P1 brand mismatch).
2. The supplied mark was cropped to its real alpha bounds and rendered as platform-sized 1×/2× resources. The combined light/dark comparison shows no clipping, background fringe, or lost detached dot.

### Verification

- `pnpm typecheck:electron` — passed.
- `pnpm --dir frontend exec vitest run ../electron/system/tray.test.ts` — 4 tests passed.
- `pnpm build:system` — passed.
- An unpacked macOS package built successfully from the local Electron distribution; `app.asar` contains the macOS template pair and both Windows light/dark 1×/2× pairs.
- Focused-region evidence was not split out because the comparison sheet is already a single-purpose, pixel-enlarged icon study.

final result: passed

---

## Empty states, agent controls, and context meter

- Source visual truth: the user-supplied workflow, board, browser-pool, publish, media, settings, and AI Studio screenshots from 2026-09-02.
- Visual baseline: the workflow empty state (one centered icon/title/description/action cluster, with no duplicate empty toolbar).
- States checked: light and dark themes, empty collection views, empty detail panes, no configured chat model, active thinking state, and a new zero-message Kimi K3 session.

## Findings and corrections

- Empty collection pages now use the workflow page's full available content box as the centering reference. Board, Browser Pool, Publish, and Media omit list-only toolbars while empty and keep their primary actions inside the centered state.
- Plugin and scheduler detail placeholders, plus the Feishu binding placeholder, now center against the remaining detail-pane height instead of a content-sized grid row.
- Settings groups retain a divider beneath their header, and a single-section settings page assigns the entire post-header row to its content. The pricing-rules and Feishu empty states therefore center inside the true remaining height without crossing the header.
- The scheduler's bound-workflow region is flat and separated by dividers rather than wrapped in an additional card.
- AI Studio replaces the unavailable model selector with a compact “Configure chat model” action, while loading and failed model queries do not flash a false unconfigured state.
- Thinking markers use a shared square flex box, and the expanded thinking header/body share the same text start. The overall loading marker and label are vertically centered on the same line.
- A new session that inherits the default provider now resolves its context-window metadata from that provider's stored model catalog. Kimi K3 reports its actual 1,048,576-token window instead of the 32,000-token fallback, changing the reproduced empty-session display from about 50% remaining to about 98% remaining.

## Verification

- Frontend DOM coverage checks the no-model navigation affordance, loading-state suppression, settings layout-class passthrough, and thinking-marker alignment.
- Backend context-breakdown coverage reproduces a session with no explicit profile and verifies catalog lookup through the resolved default profile.
- The live local API returned a 1,048,576-token window with 1,032,496 tokens free for the reproduced K3 session.

final result: passed

---

## Mosael brand migration

### Visual truth and rendered evidence

- Light icon source: `/Users/kinda/Desktop/Codex Image Sep 2, 2026, 02_55_47 PM.png` (`1254 × 1254`).
- Dark icon source: `/Users/kinda/Desktop/Codex Image Sep 2, 2026, 02_55_42 PM.png` (`1254 × 1254`).
- Wordmark source: `/Users/kinda/Desktop/Codex Image Sep 2, 2026, 02_55_38 PM.png` (`2172 × 724`).
- Light website: `docs/media/design-qa/mosael-brand/website-light-final.jpg`.
- Dark website: `docs/media/design-qa/mosael-brand/website-dark-final.jpg`.
- Dark app login: `docs/media/design-qa/mosael-brand/app-dark-final.jpg`.
- Author-link/footer state: `docs/media/design-qa/mosael-brand/website-footer-light.jpg`.
- Combined source/implementation comparison: `docs/media/design-qa/mosael-brand/brand-comparison.png`.

The website and app captures use a `1280 × 720` CSS viewport. Browser capture normalized the output to `1280 × 720` pixels. The combined comparison places all three supplied assets above the corresponding light website, dark website, and app states, so icon shape, color treatment, wordmark, and theme choice can be judged in one view.

### Findings

No actionable P0, P1, or P2 findings remain.

- Asset fidelity: the supplied raster artwork is used directly. No traced SVG, CSS approximation, or redrawn mark was introduced.
- Theme behavior: the pale icon is visible in light UI; the dark, luminous icon is visible in dark UI. Both keep their native aspect ratio and resolution.
- Brand hierarchy: the wordmark anchors the README, website hero, and footer. Compact app surfaces use the icon so labels and controls retain enough room.
- Copy and voice: the Chinese and English hero, README, login, closing CTA, and footer now share one idea—“让灵感落进时间线 / Where ideas find their timeline.” Supporting copy speaks in user tasks rather than architecture jargon.
- Author identity: `https://x.com/KindaHuax` appears in both READMEs, the website community section, footer, About, and Contact pages.
- Interaction and layout: light/dark switching preserves the mark, hero hierarchy, navigation, CTA layout, and responsive flow. The footer X links resolve to the requested URL.

### Comparison history

1. The first website render passed the assets through the Next image optimizer, which returned `400` for the supplied PNGs; the header and wordmark appeared broken (P1). Brand images were changed to direct, unoptimized delivery and rechecked.
2. The first app login render still used the previous generic film glyph in one auth state (P2). It was replaced with the shared theme-aware `BrandMark` and rechecked.
3. The final pass added a friendlier bilingual brand voice and the author X touchpoints. The production website build and browser-rendered light, dark, and footer states show no clipping, broken assets, or new layout regressions.

### Verification

- `pnpm --dir website build` — 55 static pages generated successfully.
- `pnpm --dir frontend exec vitest run` — 129 files and 818 tests passed.
- `pnpm --dir frontend build` — TypeScript and Vite production build passed.
- Browser checks confirmed the expected theme class, real `1254px`/`2172px` source dimensions, updated brand copy, and two visible author-X destinations.

final result: passed

---

## Shared agent session header design QA

### Comparison target

- Source visual truth: `/var/folders/yw/0kg9jbhj3xx00gq05_14d1lw0000gn/T/TemporaryItems/NSIRD_screencaptureui_VevbUZ/Screenshot 2026-09-02 at 00.25.43.png`
- Browser-rendered implementation: `http://localhost:5173/#/workflows`, authenticated against an isolated temporary backend with three seeded agent sessions.
- Scope: the shared `CanvasAgentChat` used by workflows, creative boards, and the editor.

### Findings

No actionable P0/P1/P2 findings remain in the requested agent header.

- Information hierarchy: the active session title is now the top-left heading content. The generic robot icon and `AI 助手` label no longer compete with the actual conversation identity.
- Long titles: the title owns the remaining header width and uses a single-line ellipsis; the new-session, dock/float, and close controls remain fixed-width.
- Session switching: clicking the flat title opens the shared session list. Search focuses automatically, filters case-insensitively, exposes an explicit no-match state, and clears when the popover closes.
- Framing: the docked panel renders with `border-0 shadow-none` and no rounded outer card. Floating mode deliberately keeps a border and radius because it needs a visible spatial boundary over the canvas.
- Popover styling: the trigger is borderless and background-free; the temporary session surface uses the existing popover token, restrained shadow, and backdrop blur rather than an input-like frame around the permanent title.
- Accessibility: the session trigger, search field, session choices, delete actions, active check mark, and empty state have stable accessible names. Keyboard focus enters the search field when the list opens.

### Browser interaction evidence

- The authenticated workflow view restored directly to its detail state and opened the shared agent panel.
- A long seeded title rendered as the active header title without displacing the three header actions.
- Opening `会话` exposed all three seeded sessions and the `搜索对话…` search box.
- Entering `工作流` reduced the list to `工作流节点整理方案`; selecting it updated the header immediately and closed the popover.
- The live docked `<aside>` computed to `border-0 shadow-none` with a `400 × 598` layout region at the tested `1280 × 720` viewport.

### Verification

- `pnpm --dir frontend exec vitest run src/components/agent/AgentSessionSwitcher.dom.test.tsx` — 3 tests passed.
- `pnpm --dir frontend build` — TypeScript and Vite production build passed.
- In-app browser DOM verification covered the long-title, open, search, filtered, switch, and docked-frame states.

final result: passed

---

## Startup loading design QA

### Comparison target

- Source visual truth: `/var/folders/yw/0kg9jbhj3xx00gq05_14d1lw0000gn/T/TemporaryItems/NSIRD_screencaptureui_OKxCRA/Screenshot 2026-09-02 at 00.14.42.png`.
- Browser-rendered implementation: `/tmp/mosael-design-qa/startup-loading-implementation-1728x1117.png`.
- Combined source/implementation comparison: `/tmp/mosael-design-qa/startup-loading-comparison.png`.
- State: initial authentication boot with an intentionally reachable-but-non-responsive backend, so the loading state remains visible without changing production timing.

### Viewport and normalization

- Source pixels: `3456 × 2234`, representing a `1728 × 1117` CSS-pixel Electron capture at 2× density.
- Implementation pixels and CSS viewport: `1728 × 1117`, device pixel ratio `1` under the explicit in-app-browser viewport override.
- Density normalization: the source was downsampled to `1728 × 1117`; source and implementation were then stacked at equal pixel dimensions.
- The source uses the user's saved dark theme while the isolated browser origin defaults to light. Layout, hierarchy, and copy are compared directly; theme colors are assessed through the same semantic tokens used by the rest of the application rather than by pretending the two palettes are pixel-equivalent.

### Findings

No actionable P0/P1/P2 findings remain in the requested startup state.

- Fonts and typography: the single tiny caption is replaced by a clear two-level hierarchy using existing responsive UI type tokens. The primary state remains concise, with an explanatory secondary line that does not claim a fabricated percentage.
- Spacing and layout rhythm: the status cluster remains centered but now has a 72 px visual anchor, a compact 20 px gap, and enough internal width to read as intentional rather than stranded text.
- Colors and visual tokens: the mark, ring, foreground, muted foreground, border, and surface use existing semantic tokens. The light implementation capture verifies contrast; dark rendering follows the same already-established token pairs visible in the source application.
- Image quality and asset fidelity: no raster image or approximation was introduced. The existing vector `BrandMark` and the application's standard Lucide loading icon are reused.
- Copy and content: the state now distinguishes backend connection from the later workspace restoration phase. Both Chinese and English messages are present.
- Accessibility and motion: the cluster exposes `role=status`, `aria-live=polite`, and `aria-busy=true`. The standard Mosael spinner is covered by the repository-wide `prefers-reduced-motion` override, while the textual status remains understandable without motion.

### Full-view and focused-region evidence

The equal-size side-by-side comparison shows that the revised cluster keeps the source's calm full-screen composition while making the active state materially more legible. A separate focused crop was unnecessary: the only content on the screen is the centered status cluster, and it is readable in the full-resolution implementation capture.

### Comparison history

1. Baseline: a very small, low-contrast sentence alone in the center left most of the wait state visually empty and provided no animated evidence that the app was still working.
2. Revised capture: a branded center mark, restrained indeterminate spinner, primary status, and secondary explanation provide activity and hierarchy without adding a false progress meter. The browser console contained no warnings or errors.

### Verification

- `pnpm --dir frontend test -- StartupLoading.dom.test.tsx` — 127 files and 812 tests passed.
- `pnpm --dir frontend build` — TypeScript and Vite production build passed.
- Browser state and copy were verified through the status DOM; the implementation screenshot was captured at the normalized source viewport; console warnings/errors: none.

final result: passed

---

## Transcript row design QA

### Comparison target

- Source visual truth: `/var/folders/yw/0kg9jbhj3xx00gq05_14d1lw0000gn/T/TemporaryItems/NSIRD_screencaptureui_C8rYpV/Screenshot 2026-09-01 at 23.57.43.png`
- Browser-rendered implementation: the authenticated editor is an Electron-only state; the in-app browser reached the unauthenticated login screen and was not used as visual evidence.
- Implementation screenshot: `/var/folders/yw/0kg9jbhj3xx00gq05_14d1lw0000gn/T/com.openai.sky.CUAService/Mosael Screenshot 2026-09-01 at 11.59.57 PM.jpeg`
- Focused implementation crop: `/tmp/mosael-design-qa/transcript-row-implementation.png`
- Combined source/implementation comparison: `/tmp/mosael-design-qa/transcript-row-comparison.png`
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

The combined comparison at `/tmp/mosael-design-qa/transcript-row-comparison.png` places the user's reported row above the revised rendered row. The revised row removes the oversized body line box, aligns left metadata to the first text line, and hides the action rail in the resting state.

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

---

## Asset audio preview player

- Source visual truth: `/var/folders/yw/0kg9jbhj3xx00gq05_14d1lw0000gn/T/TemporaryItems/NSIRD_screencaptureui_iHiRmT/Screenshot 2026-09-02 at 15.46.59.png`
- Rendered implementation: `/tmp/mosael-audio-preview-dark-1076x488.png`
- Combined comparison: `/tmp/mosael-audio-preview-comparison.png`
- State: dark theme, asset library, audio asset detail dialog open
- Viewport: 1076 × 488 CSS px
- Density normalization: source 2152 × 976 px at inferred 2× density, normalized to 1076 × 488 px; implementation 1076 × 488 px at 1× density

## Findings

No actionable P0, P1, or P2 issues remain.

- Fonts and typography: the existing dialog hierarchy, labels, metadata, and compact player time remain consistent with the product typography.
- Spacing and layout rhythm: the replacement stays within the original audio-control footprint, remains centered, and does not change the modal or metadata layout. The player has no shadow.
- Colors and visual tokens: the controls use the existing primary, muted foreground, and border colors, with a low-opacity surface suitable for the dark media stage.
- Image quality and asset fidelity: no image assets were introduced or replaced; Lucide icons match the product's existing control language.
- Copy and content: existing localized play, pause, mute, and unmute labels are reused.

The visible difference from the supplied screenshot is intentional: the browser-native gray control is replaced by Mosael's shared player with a primary play button, branded progress bar, elapsed/total time, and mute control.

## Interaction evidence

- Autoplay reached the playing state when the dialog opened.
- Play/pause toggled successfully.
- Mute/unmute toggled successfully.
- No browser console errors were recorded during the interaction check.

## Focused comparison

The audio-control region was inspected in the combined comparison. No additional crop was needed because the normalized full view keeps the player controls and surrounding modal layout legible.

## Comparison history

- Initial pass: no P0/P1/P2 issues found; no visual correction iteration was required.

## Implementation checklist

- [x] Replace native audio controls with the shared custom player.
- [x] Preserve autoplay, playback, seeking, elapsed/total time, and mute behavior.
- [x] Verify the dark-theme modal at the source screenshot's normalized viewport.
- [x] Verify interaction state and console output.

final result: passed
