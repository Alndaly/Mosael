# Changelog

This file records user-visible release highlights. GitHub Releases contains the complete generated
commit list and downloadable artifacts.

## Unreleased

### Added

- Extended the Chrome Side Panel from three hard-coded sites to every HTTP(S) video URL recognized
  by the installed yt-dlp extractor registry, while preserving native caption adapters for YouTube
  and Bilibili.
- Added a lightweight authenticated URL-support endpoint and optional Browser Pool identity selection
  for restricted, signed-in, proxied, or region-sensitive imports and automatic transcription.
- Added a registry-wide contract test that checks every canonical yt-dlp extractor sample without
  making network requests.

### Changed

- Separated backend import/transcription capability from in-page playback capability: custom,
  embedded, or protected players can still be imported when yt-dlp supports them, while seek and
  frame controls remain disabled unless a usable HTML5 video is present.
- Replaced site-specific manifest host lists with explicit HTTP(S) page access, required for generic
  player discovery and clean video-frame fallback capture.

### Fixed

- Replaced opaque yt-dlp 403, 412, login, geo, and IP-block failures with guidance to select a
  matching Browser Pool identity or proxy.

## [0.26.10] - 2026-09-02

### Added

- Added Pornhub video-page support with Open Studio transcription fallback and stable source-URL
  recovery, so completed transcripts are reused instead of generated again.
- Added word-level transcript navigation for Open Studio ASR results while preserving readable
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
  YouTube translation tracks before using Open Studio translation.
- Added one-click Open Studio download and speech transcription when a video page has no captions.
- Added a localized React Side Panel that follows Chrome or can be pinned to Simplified Chinese or
  English, using Tailwind CSS v4 and shadcn/ui controls.

### Fixed

- Fixed Chrome rejecting account connections with `Failed to execute 'fetch' on 'Window': Illegal invocation`.
- Replaced raw empty YouTube JSON failures with a clear no-caption state and kept undelimited cues
  active for playback following.

## [0.26.8] - 2026-09-02

### Added

- Added a Chrome 116+ Side Panel extension for YouTube and Bilibili transcripts, timestamp seeking,
  transcript translation, current-video import, and visible-player frame capture into the Open
  Studio media library.

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

[0.26.10]: https://github.com/Alndaly/OpenStudio/releases/tag/v0.26.10
[0.26.9]: https://github.com/Alndaly/OpenStudio/releases/tag/v0.26.9
[0.26.8]: https://github.com/Alndaly/OpenStudio/releases/tag/v0.26.8
[0.26.7]: https://github.com/Alndaly/OpenStudio/releases/tag/v0.26.7
