# Changelog

This file records user-visible release highlights. GitHub Releases contains the complete generated
commit list and downloadable artifacts.

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

[0.26.9]: https://github.com/Alndaly/OpenStudio/releases/tag/v0.26.9
[0.26.8]: https://github.com/Alndaly/OpenStudio/releases/tag/v0.26.8
[0.26.7]: https://github.com/Alndaly/OpenStudio/releases/tag/v0.26.7
