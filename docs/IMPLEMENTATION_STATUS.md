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

### Undo / Redo (plan §10.2)

- Alembic 0002 history columns; undo applies operation inverses, redo re-applies; fresh edits invalidate the redo stack; every undo/redo is itself an operation + revision.
- Editor toolbar buttons + ⌘Z / ⇧⌘Z; can_undo/can_redo on sequence responses.

### Transcripts (plan Phase 5 MVP)

- Alembic 0003: transcripts / transcript_segments / transcript_tokens / clip_transcript_refs.
- PUT/GET /api/assets/{id}/transcript; attaching replaces the prior transcript; transcripts are analysis results, never a second edit state.
- Pure projection kernel (transcriptProjection.ts, tested) maps asset segments through clip src ranges; editor left panel 素材/逐字稿 tabs with click-to-seek and playhead highlight.

### MCP (plan §17 minimal)

- backend/mcp_server.py (stdio, FastMCP): list_projects / list_assets / inspect_sequence returning product-semantic summaries; verified with a real MCP stdio client. See docs/MCP.md.

### Local auth + workspace scoping (plan Phase 2)

- Local accounts (PBKDF2 password hashes, opaque session tokens in auth_sessions, Alembic 0004); register/login/me/logout; first account adopts pre-auth workspaces.
- Every router behind authentication; workspace membership enforced across projects/assets/sequences/jobs/generation/scheduler — foreign or unknown resources return 404 (plan §9.3); media endpoints accept ?token= for <video>/<img>.
- Login/register screen gates the app; token in localStorage; 401 anywhere drops back to login; account section with sign-out in Settings; MCP server passes MIBU_TOKEN.
- Isolation tests: second user sees no foreign workspaces, all cross-user access 404s.

### Desktop packaging (plan Phase 14, macOS)

- Backend packaged with PyInstaller (run_backend.py → dist/mibu-backend, 127.0.0.1 only).
- Production Electron shell: reuses an already-healthy backend or spawns the packaged binary, waits on /api/health (30s), error dialogs on failure/crash, kills the backend on quit.
- electron-builder config in root package.json (mac dir/dmg targets; win nsis config prepared, unverified); frontend built with relative base for file:// loading; CORS opened for the file:// origin — auth still gates every request.
- Verified: `pnpm build:mac` produces Mibu.app (~275MB) that launches its embedded backend (health ok), and quitting leaves no orphan mibu-backend and releases the port.

### Generation providers (plan Phase 10)

- Pluggable provider contract (validate/generate with guardrails: num_images ≤ 4, duration ≤ 10s, resolution whitelist; sanitized errors so keys never leak) in app/ai/providers.
- Real adapters: qwen-image via DashScope async tasks, Seedance via Volcano ARK content-generation tasks (pure payload builders unit-tested).
- Mock image/video providers synthesize media locally with ffmpeg so the whole pipeline runs offline.
- Credentials table (Alembic 0005) + masked settings API and Settings UI for provider keys.
- Generation runner thread: submit→poll→download→register as generated asset + generated_assets row + job lifecycle; results are draggable timeline material immediately.
- AI Studio rebuilt: prompt composer, data-driven model pills, live-polling queue with result thumbnails.

### Transcript-driven editing (apply_transcript_edit)

- cut_clip_range operation removes a source range from a clip: split into left + ripple-closed right, edge cuts trim, full cuts delete — recorded as one invertible apply_transcript_edit operation (undo restores the original clip, redo re-applies).
- POST /sequences/{id}/clips/{clip_id}/cut-range; transcript panel segments carry a hover cut action wired through the projection's src range.

### Audio playback + waveforms

- Waveform cache (plan §8): mono peak buckets extracted with ffmpeg at import/export-registration, stored beside the asset, served via GET /api/assets/{id}/waveform.
- Audio-track clips render their sliced waveform (pure slicePeaks/downsample kernel, tested) as an SVG inside the clip.
- Monitor drives a hidden audio element in lockstep with the active audio-track clip (gain/mute honored); playback clock switched from rAF to interval so it survives occluded/background windows.

## Next

- Timeline preview via RenderPlan-backed proxy renders for multi-track scenes.
- Mutating MCP tools behind confirmation cards and permission levels (§17.2/§17.4).
- Sandboxed plugin execution adapters.
- A real scheduler runner process claiming due tasks.
- Windows packaging + smoke test (mac done); app icon, code signing, auto-update.

## Frontend Rules

- Use TailwindCSS and local shadcn/ui components for all interactive controls.
- Do not use native browser dialogs such as `alert`, `confirm`, or `prompt`.
- Keep all user-visible copy behind the i18n preference layer.
- Preserve light and dark theme support for every new surface.
- Timeline math lives in `domain/timeline/geometry.ts` as tested pure functions; components never inline geometry.
- Server entities stay in React Query; Zustand holds only drafts and transient UI state.
