# Changelog

This file records user-visible release highlights. GitHub Releases contains the complete generated
commit list and downloadable artifacts.

## Unreleased

### Fixed

- Kept screen and camera streams attached to the live preview when the recorder changes from its setup dialog
  into the floating controller, preventing both preview panes from turning black during an active recording.
- Prevented requested system-audio capture from silently degrading into a mute screen recording when the macOS
  sharing picker returns no live audio track, and now explains how to retry with audio sharing enabled.

### Added

- Added an explicit recording-permission flow: camera and microphone access is now requested only after a user
  action, denied screen/system-audio capture offers the relevant operating-system settings and retry actions,
  and packaged macOS builds declare all camera, microphone, and system-audio usage descriptions.
- Added synchronized screen-and-camera recording to the media library and editor media pool, producing
  two independent assets from one recording session instead of baking the camera into the screen capture.
- Added an optional, remembered camera mirror that flips both the live preview and saved camera asset while
  leaving the independently recorded screen asset unchanged.
- Kept active recordings alive across app navigation and collapsed the recorder into a non-blocking controller,
  so the rest of Mosael remains usable while captured files retain their original workspace or project destination.
- Added optional device-audio capture to screen recordings, including Windows loopback grants and the macOS
  packaged-app permission required by supported system sharing pickers.
- Added clip-level circular and rounded-rectangle video masks plus configurable drop shadows, with matching
  Canvas preview, undoable project persistence, and FFmpeg export rendering.

## [1.0.0-beta1] - 2026-09-03

### Changed

- Consolidated compatibility handling around one rule: owned data migrates once to the current shape,
  while mixed-version desktop components are not supported; the documented direct-upgrade floor is v0.1.0.
- Migrated legacy board job/error state into the current `run` object at startup and removed the matching
  frontend dual-read branches, the obsolete TTS source migration, and the generation-model type alias.
- Stopped guessing that workspaces named “Workspace” or “默认工作区” are system defaults, preserving names
  exactly as their owners entered them.
- Retired the legacy `openstudio://` deep-link scheme; desktop navigation now accepts only the registered
  `mosael://` protocol.
- Updated the homepage hero and editing chapter to use the supplied current editor capture, and added a
  dedicated media-management chapter with the supplied library and recording view.
- Extended the release gate to build the browser extension and bilingual website, and kept beta tags as
  GitHub prereleases instead of replacing the latest stable release.

### Fixed

- Made pre-Mosael browser and extension storage migration remove its legacy source after a successful copy,
  preventing cleared sessions, preferences, or extension connections from returning on the next launch.
- Migrated `open-studio.db` and its SQLite sidecars inside explicitly configured data directories, with
  transactional rollback, bootstrap backup, established-library conflict protection, and fail-closed startup.
- Portaled the documentation search modal outside the blurred floating header so its dimming layer and
  click-away target cover the full viewport, and added a rhythm-matched divider below the app rail logo.
- Recovered pre-Mosael backend libraries and Electron user data even when first launch had already
  created the new directories, with automatic one-time migration, database sidecar renaming, conflict
  protection, and recoverable backups of the replaced bootstrap directories.
- Extended inner-page hero backgrounds behind the floating navigation instead of leaving a separate page-color
  strip above Workflows, Plugins, and plugin details.
- Removed redundant screenshot shells from homepage product chapters and tightened the Mosael wordmark asset so
  footer alignment, navigation sizing, and closing-brand spacing follow the visible artwork rather than transparent padding.
- Increased footer group and link spacing so the lower navigation remains easy to scan in both languages.
- Normalized Settings section rhythm and full-width form rows, with the current password separated from
  the new-password pair so account editing follows the same hierarchy as the other settings pages.
- Serialized creative-board autosaves, waited for server confirmation before clearing pending state, and
  retained the latest canvas for a later retry after a failed write.
- Released AI sidecar steering channels on provider errors, callback failures, timeouts, and aborts as well
  as successful turns, preventing stale sessions and child processes from lingering.

## [0.27.6] - 2026-09-02

### Changed

- Rebuilt the Mosael website around a centered editorial hero, a larger product stage, open full-width
  chapters, and a more distinctive violet-to-coral brand rhythm across light and dark themes.
- Reworked the product story and bilingual headline around a continuous creative path from scattered ideas
  to a finished story, while keeping the real Infinite Canvas, editor, agent, and workflow captures central.
- Carried the same open, lightly divided visual language through Workflows, Plugins, plugin details,
  documentation, mobile navigation, not-found pages, and the footer instead of enclosing every section in a card.
- Replaced the edge-attached site bar with a fixed translucent capsule that floats over the homepage color,
  and removed the redundant Infinite Canvas navigation tab.

### Fixed

- Corrected active navigation matching so Product is highlighted only on the homepage and Docs stays active
  across every documentation route.
- Prevented the mobile navigation overlay from being clipped by the blurred header container.
- Replaced the unusable generation composer state with direct model-configuration actions in both the composer
  and engine panel when no image or video generation model is available.

## [0.27.5] - 2026-09-02

### Fixed

- Restored the plugin marketplace by replacing its retired website endpoint with a reachable
  published registry.
- Prevented marketplace requests from inheriting AI-provider retry behavior, so an unavailable feed
  now reaches a clear error state instead of leaving the dialog on loading placeholders for multiple
  retry cycles.

## [0.27.4] - 2026-09-02

### Changed

- Rebuilt the bilingual Mosael website around a flowing product-story timeline, with a calmer
  warm-white and violet visual system, deliberate editorial spacing, and responsive navigation.
- Gave Infinite Canvas, timeline editing, the AI agent, and visual workflows equal prominence using
  current product captures, while keeping the local-first promise and KindaHuaX attribution clear.
- Removed the outdated knowledge-base claim and the nonexistent product X account from website copy.

## [0.27.3] - 2026-09-02

### Changed

- Strengthened the visual hierarchy across Settings with a clearer page, section, item, and
  supporting-copy type scale, plus more deliberate row and section spacing.
- Kept controls, dividers, and the flat panel structure unchanged so the denser information remains
  familiar while becoming easier to scan.

## [0.27.2] - 2026-09-02

### Changed

- Replaced the macOS menu-bar and Windows notification-area icons with the supplied Mosael mark,
  using native 1×/2× resources sized for persistent system status surfaces.
- Made the Windows tray mark follow the system appearance with dedicated dark-on-light and
  light-on-dark variants, while macOS uses a template image for automatic menu-bar contrast.

## [0.27.1] - 2026-09-02

### Changed

- Standardized empty collections on the workflow-page pattern: the board, Browser Pool, publish,
  media, plugin, scheduler, and supported settings states now center within their true remaining
  content height, while list-only toolbars stay hidden until they are useful.
- Kept settings section headers visually separate from their content and removed the extra frame
  around a scheduled task's bound workflow.
- Replaced the AI Studio model picker with a direct configuration action when no chat model exists,
  and aligned expanded thinking and loading markers with their text.

### Fixed

- Resolved inherited default-provider model metadata before calculating context usage, so a new
  Kimi K3 conversation uses its real catalog window instead of incorrectly reporting only half of
  the fallback window as available.

## [0.27.0] - 2026-09-02

### Added

- Extended the Chrome Side Panel from three hard-coded sites to every HTTP(S) video URL recognized
  by the installed yt-dlp extractor registry, while preserving native caption adapters for YouTube
  and Bilibili.
- Added a lightweight authenticated URL-support endpoint and optional Browser Pool identity selection
  for restricted, signed-in, proxied, or region-sensitive imports and automatic transcription.
- Added a registry-wide contract test that checks every canonical yt-dlp extractor sample without
  making network requests.

### Changed

- Renamed the product, application packages, desktop shell, backend, website, browser extension,
  plugin format, workflow format, environment variables, deep links, and documentation to Mosael.
- Replaced the previous mark with the supplied Mosael identity: separate light and dark app icons
  now follow the active theme, while the supplied wordmark appears in the README and website.
- Refined the bilingual README, website, and sign-in copy around the shared “ideas find their
  timeline” voice, and added the author's X profile to the main project touchpoints.
- Added one-time compatibility migration for existing local data, Electron user data, environment
  overrides, browser-extension sessions, frontend preferences, plugin manifests, workflow files,
  and deep links created before the Mosael rename.
- Separated backend import/transcription capability from in-page playback capability: custom,
  embedded, or protected players can still be imported when yt-dlp supports them, while seek and
  frame controls remain disabled unless a usable HTML5 video is present.
- Replaced site-specific manifest host lists with explicit HTTP(S) page access, required for generic
  player discovery and clean video-frame fallback capture.

### Fixed

- Replaced opaque yt-dlp 403, 412, login, geo, and IP-block failures with guidance to select a
  matching Browser Pool identity or proxy.
- Routed every image presentation surface through the browser-compatible preview endpoint, fixing
  broken HEIC/HEIF rendering in asset details, the editor compositor, compare view, boards, AI
  galleries, frame slots, and agent tool results while preserving original-file downloads.
- Replaced the asset-detail dialog's browser-native audio controls with the shared Mosael audio
  player, keeping playback, seeking, elapsed time, mute, and autoplay behavior consistent.

## [0.26.10] - 2026-09-02

### Added

- Added Pornhub video-page support with Mosael transcription fallback and stable source-URL
  recovery, so completed transcripts are reused instead of generated again.
- Added word-level transcript navigation for Mosael ASR results while preserving readable
  sentence grouping and sentence-level fallback for legacy data.

### Fixed

- Changed current-frame import to prefer decoded video pixels and exclude HTML playback controls;
  cross-origin media now uses a temporary overlay-free capture fallback.
- Hardened Bilibili subtitle fetching against translated pages, expired resources, and CORS/network
  failures, with localized error states instead of raw `Failed to fetch` messages.
- Replaced remaining native selects and shadow-heavy extension styling with the shared Tailwind and
  shadcn/ui treatment.
- Made direct agent messages and queued-message draining share one atomic session claim, preventing
  rare duplicate turns when a new message arrives as the previous turn finishes.

## [0.26.9] - 2026-09-02

### Added

- Added playback-synced bilingual subtitles to the Chrome Side Panel, preferring site-provided or
  YouTube translation tracks before using Mosael translation.
- Added one-click Mosael download and speech transcription when a video page has no captions.
- Added a localized React Side Panel that follows Chrome or can be pinned to Simplified Chinese or
  English, using Tailwind CSS v4 and shadcn/ui controls.

### Fixed

- Fixed Chrome rejecting account connections with `Failed to execute 'fetch' on 'Window': Illegal invocation`.
- Replaced raw empty YouTube JSON failures with a clear no-caption state and kept undelimited cues
  active for playback following.

## [0.26.8] - 2026-09-02

### Added

- Added a Chrome 116+ Side Panel extension for YouTube and Bilibili transcripts, timestamp seeking,
  transcript translation, current-video import, and visible-player frame capture into the Mosael
  media library.

## [0.26.7] - 2026-09-02

### Added

- Added the AI assistant to the editor and made the shared workspace assistant a docked column by
  default, with an optional floating mode.
- Made the assistant's current conversation title the header control, with searchable conversation
  switching and creation/deletion kept in the same compact surface.
- Added a richer animated startup state while the desktop shell connects to the backend.

### Changed

- Reworked transcript sentence rows so timestamps, speakers and the first text line align, long text
  wraps in full, and contextual actions no longer reserve empty width.
- Flattened settings sections and lists, using separators instead of nested card borders.
- Split jobs, notifications, scheduler, workflows and boards into domain-owned backend models,
  schemas and frontend API modules while preserving the public assembly entry points.

### Fixed

- Preserved workflow, board, scheduler, plugin and media detail context during reload instead of
  flashing each section's list page first.
- Prevented the editor assistant from covering the workspace when opened.

[1.0.0-beta1]: https://github.com/Alndaly/Mosael/releases/tag/v1.0.0-beta1
[0.27.6]: https://github.com/Alndaly/Mosael/releases/tag/v0.27.6
[0.27.5]: https://github.com/Alndaly/Mosael/releases/tag/v0.27.5
[0.27.4]: https://github.com/Alndaly/Mosael/releases/tag/v0.27.4
[0.27.3]: https://github.com/Alndaly/Mosael/releases/tag/v0.27.3
[0.27.2]: https://github.com/Alndaly/Mosael/releases/tag/v0.27.2
[0.27.1]: https://github.com/Alndaly/Mosael/releases/tag/v0.27.1
[0.27.0]: https://github.com/Alndaly/Mosael/releases/tag/v0.27.0
[0.26.10]: https://github.com/Alndaly/Mosael/releases/tag/v0.26.10
[0.26.9]: https://github.com/Alndaly/Mosael/releases/tag/v0.26.9
[0.26.8]: https://github.com/Alndaly/Mosael/releases/tag/v0.26.8
[0.26.7]: https://github.com/Alndaly/Mosael/releases/tag/v0.26.7
