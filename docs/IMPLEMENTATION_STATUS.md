# Implementation Status

## Done

### Backend

- Clean monorepo skeleton with FastAPI backend and Alembic migrations.
- Real relational models for workspace, project, asset, sequence, track, clip, jobs, events, scheduler, generated assets, plugins.
- CRUD APIs for workspaces, projects, assets, sequences.
- SequenceOperation edit kernel: insert_clip, move_clip (track-kind checked), trim_clip, delete_clip — each validates invariants and records `sequence_operations` + `sequence_revisions` rows.
- Asset import with ffprobe media info, best-effort ffmpeg thumbnail, `GET /api/assets/{id}/file` (Range-capable) and `/thumbnail` serving.
- Job APIs as the common background-task surface; generation model catalog and generation job APIs; scheduler APIs; plugin manifest scanning with deny-by-default permission grants.
- pytest coverage: edit flow, move/trim/delete + validation errors, file-backed imports, generation jobs, scheduled runs, plugins.

### Frontend

- Instrument-panel design system in `design/tokens.css`: neutral cold-gray canvas, white panels, refined blue primary, semantic track colors (video/audio/subtitle/overlay), editor surface tokens (monitor/ruler/playhead/lanes), mono tabular timecode, separately calibrated dark theme.
- App shell: 56px icon rail with the plan's 8 primary sections (首页/素材/剪辑/AI Studio/批量/发布/知识库/设置) plus scheduler/plugins secondary entries, tooltips, topbar crumb, quick theme/language toggles.
- Real editor (four-region NLE layout):
  - Timeline: adaptive timecode ruler, scrubbable playhead, zoom (buttons + ctrl/cmd-wheel), snap toggle, colored per-kind clips, pointer drag move, edge trim handles, selection, drop-to-insert from pool.
  - Pure geometry kernel `domain/timeline/geometry.ts` with 21 Vitest cases.
  - Monitor: rAF playback clock, `<video>` synced to the active video-track clip, black gaps, image clip rendering, transport bar.
  - Media pool (thumbnails, drag + double-click append) and Inspector (ranges, speed/gain, delete).
  - State split per plan §14.2: server truth in React Query, drag drafts + transient UI in Zustand.
- Home (project cards), Media library (thumbnail grid), Settings (preferences + backend info); Batch/Publish/KB as crafted planned states.
- i18n (zh/en) and light/dark across every surface; OpenAPI-generated types only.

### Verified end-to-end (browser)

Workspace → project → import (thumbnails generated) → create timeline → double-click/drag insert → drag move (+3s), end trim (−2s), delete via keyboard → ruler seek renders the exact frame → space playback runs to end and stops → reload restores state (revision 6).

### Render / Export (plan §11, Phase 7)

- RenderPlan kernel: pure, hashable clip/gap segment plans with unit tests; overlaps and missing files rejected.
- RenderExecutor: single-invocation FFmpeg render (segments normalized to output format, gaps as black+silence, concat, x264/aac) with -progress reporting.
- Export flow: export button in the timeline toolbar → render job with live progress → mp4 in ~/.mibu-new/exports/ → result registered as an exported asset (thumbnail included) that appears in the media pool and library.
- Test isolation: tests run in a temp MIBU_DATA_DIR (conftest) so the suite never touches the live database.

## Next

- Undo/redo surfaced in the editor (operation log already records history).
- Audio track playback in the monitor; waveforms in pool and clips.
- Timeline preview via RenderPlan-backed proxy renders for multi-track scenes.
- Transcript tables and projection views (Phase 5).
- Sandboxed plugin execution adapters; real generation provider adapters.
- A real scheduler runner process claiming due tasks.
- Electron packaging pass (Phase 14).

## Frontend Rules

- Use TailwindCSS and local shadcn/ui components for all interactive controls.
- Do not use native browser dialogs such as `alert`, `confirm`, or `prompt`.
- Keep all user-visible copy behind the i18n preference layer.
- Preserve light and dark theme support for every new surface.
- Timeline math lives in `domain/timeline/geometry.ts` as tested pure functions; components never inline geometry.
- Server entities stay in React Query; Zustand holds only drafts and transient UI state.
