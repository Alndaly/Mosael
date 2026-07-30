# Implementation Status

## Done

### Backend

- Clean monorepo skeleton with a FastAPI backend; schema is `create_all` + `_migrate_*` (see ARCHITECTURE.md).
- Real relational models for workspace, project, asset, sequence, track, clip, jobs, events, scheduler, generated assets, plugins.
- CRUD APIs for workspaces, projects, assets, sequences.
- SequenceOperation edit kernel: insert_clip, move_clip (track-kind checked), trim_clip, delete_clip — each validates invariants and records `sequence_operations` + `sequence_revisions` rows.
- Asset import with ffprobe media info, best-effort ffmpeg thumbnail, `GET /api/assets/{id}/file` (Range-capable) and `/thumbnail` serving.
- Job APIs as the common background-task surface; generation model catalog and generation job APIs; scheduler APIs; plugin manifest scanning with deny-by-default permission grants.
- pytest coverage: edit flow, move/trim/delete + validation errors, file-backed imports, generation jobs, scheduled runs, plugins.

### Frontend

- Instrument-panel design system in `design/tokens.css`: neutral cold-gray canvas, white panels, refined blue primary, semantic track colors (video/audio/subtitle/overlay), editor surface tokens (monitor/ruler/playhead/lanes), mono tabular timecode, separately calibrated dark theme.
- App shell: 56px icon rail with primary sections (首页/素材/剪辑/AI Studio/发布/知识库/设置) plus secondary entries 工作流/浏览器池/定时任务/插件, tooltips, topbar crumb, quick theme/language toggles. (The old 批量 tab was removed — batch runs are now covered by workflows.)
- Real editor (four-region NLE layout):
  - Timeline: adaptive timecode ruler, scrubbable playhead, zoom (buttons + ctrl/cmd-wheel), snap toggle, colored per-kind clips, pointer drag move, edge trim handles, selection, drop-to-insert from pool.
  - Pure geometry kernel `domain/timeline/geometry.ts` with 21 Vitest cases.
  - Monitor: rAF playback clock, `<video>` synced to the active video-track clip, black gaps, image clip rendering, transport bar.
  - Media pool (thumbnails, drag + double-click append) and Inspector (ranges, speed/gain, delete).
  - State split per plan §14.2: server truth in React Query, drag drafts + transient UI in Zustand.
- Home (project cards), Media library (thumbnail grid), Settings (preferences + backend info); Publish/KB as crafted planned states.
- i18n (zh/en) and light/dark across every surface; OpenAPI-generated types only.

### Verified end-to-end (browser)

Workspace → project → import (thumbnails generated) → create timeline → double-click/drag insert → drag move (+3s), end trim (−2s), delete via keyboard → ruler seek renders the exact frame → space playback runs to end and stops → reload restores state (revision 6).

### Render / Export (plan §11, Phase 7)

- RenderPlan kernel: pure, hashable clip/gap segment plans with unit tests; overlaps and missing files rejected.
- RenderExecutor: single-invocation FFmpeg render (segments normalized to output format, gaps as black+silence, concat, x264/aac) with -progress reporting.
- Export flow: export button in the timeline toolbar → render job with live progress → mp4 in ~/.open-studio/exports/ → result registered as an exported asset (thumbnail included) that appears in the media pool and library.
- Test isolation: tests run in a temp OPEN_STUDIO_DATA_DIR (conftest) so the suite never touches the live database.

### Undo / Redo (plan §10.2)

- Schema history columns; undo applies operation inverses, redo re-applies; fresh edits invalidate the redo stack; every undo/redo is itself an operation + revision.
- Editor toolbar buttons + ⌘Z / ⇧⌘Z; can_undo/can_redo on sequence responses.

### Transcripts (plan Phase 5 MVP)

- Schema: transcripts / transcript_segments / transcript_tokens / clip_transcript_refs.
- PUT/GET /api/assets/{id}/transcript; attaching replaces the prior transcript; transcripts are analysis results, never a second edit state.
- Pure projection kernel (transcriptProjection.ts, tested) maps asset segments through clip src ranges; editor left panel 素材/逐字稿 tabs with click-to-seek and playhead highlight.

### MCP (plan §17 minimal)

- backend/mcp_server.py (stdio, FastMCP): list_projects / list_assets / inspect_sequence returning product-semantic summaries; verified with a real MCP stdio client. See docs/MCP.md.

### Local auth + workspace scoping (plan Phase 2)

- Local accounts (PBKDF2 password hashes, opaque session tokens in auth_sessions); register/login/me/logout; first account adopts pre-auth workspaces.
- Every router behind authentication; workspace membership enforced across projects/assets/sequences/jobs/generation/scheduler — foreign or unknown resources return 404 (plan §9.3); media endpoints accept ?token= for <video>/<img>.
- Login/register screen gates the app; token in localStorage; 401 anywhere drops back to login; account section with sign-out in Settings; MCP server passes OPEN_STUDIO_TOKEN.
- Isolation tests: second user sees no foreign workspaces, all cross-user access 404s.

### Desktop packaging (plan Phase 14, macOS)

- Backend packaged with PyInstaller (run_backend.py → dist/open-studio-backend, 127.0.0.1 only).
- Production Electron shell: reuses an already-healthy backend or spawns the packaged binary, waits on /api/health (30s), error dialogs on failure/crash, kills the backend on quit.
- electron-builder config in root package.json (mac dir/dmg targets; win nsis config prepared, unverified); frontend built with relative base for file:// loading; CORS opened for the file:// origin — auth still gates every request.
- Verified: `pnpm build:mac` produces Open Studio.app (~275MB) that launches its embedded backend (health ok), and quitting leaves no orphan open-studio-backend and releases the port.

### UI refinement pass + agent capabilities

- Token-level streaming chat: pi sidecar streams partial deltas → per-session SSE endpoint → live bubble; Streamdown renders all assistant markdown (tables/code/CJK, unterminated-block safe).
- Context menus everywhere (projects/assets/pool/sessions/clips) with rename/delete modals (no native dialogs); full CRUD APIs for projects/assets (in-use guard)/sessions; scheduler rows gain pause/enable + delete; empty states center vertically.
- Provider profiles (schema): multiple named provider accounts with vendor presets (DashScope/ARK/Kimi/MiniMax/OpenAI/compatible), base_url + default model, enable toggle; legacy credentials remain as fallback; Settings UI rebuilt around profiles.
- Asset analysis: images direct, videos frame-sampled (ffmpeg) into OpenAI-compatible multimodal chat — works with Kimi & MiniMax profiles; POST /assets/{id}/analyze + analyze_asset MCP tool; chat composer supports file attachments that land as assets and are referenced in the message for the agent.

### Agent host layer + Feishu binding

- Open Studio hosts a specialized external coding-agent (user decision — opencode-style, not a homegrown loop): agent_sessions/agent_messages (schema), pi sidecar adapter (Node embedding pi-agent-core; tools call back over REST with a minted service token; continuity via serialized adapter_state; specialized system prompt teaching the confirmation contract); single-flight turns, errors become assistant messages.
- Chat Workspace in AI Studio (对话/生成 tabs): sessions, bubble thread, thinking indicator, composer. Verified with a real agent turn calling list_assets.
- Feishu binding ported from mibu-video: lark-oapi long-connection worker (one child process per bot), tenant-token send, message dedupe + mention stripping, chats map to agent sessions (external_key feishu:bot:chat) with capability-tier prompts; 扫码一键创建 via device-authorization grant + manual App ID/Secret; Settings section with QR, bot list, status, capability; autostart on app launch, cleanup on shutdown.

### Mutating MCP tools + confirmation cards (plan §16.2/§17.2/§17.4)

- tool_confirmations table (schema) with permission levels (edit / ai-cost / render-cost); pending → approved/rejected → executed/failed lifecycle.
- Confirmation kernel validates payloads up front and executes only on approval: edit_timeline applies operation batches through SequenceOperations (undoable), render_sequence starts the export job, generate_image/video dispatch the provider runner.
- MCP tools: edit_timeline, render_sequence, generate_image, generate_video (all return pending confirmations) + get_confirmation for polling.
- Global confirmation card stack in the UI: requesting agent, permission badge, operation details, approve/reject; approvals refresh sequences/assets/jobs.

### Multi-track + PiP (plan Phase 8) & scheduler runner (Phase 11)

- add_track / remove_track / set_clip_effect SequenceOperations (undo/redo supported); POST/DELETE /sequences/{id}/tracks, PATCH clips/{id}/effects.
- RenderPlan carries overlay layers (upper video tracks → PiP items with x/y/scale from clip.effects.pip) and audio-track mix items (gain honored, muted skipped); executor renders overlays with enable-windows and mixes audio via amix; export duration covers audio/overlay tails.
- Editor: add-track buttons, remove-empty-track on labels, monitor PiP preview via positioned overlay video, inspector PiP position/size presets.
- Scheduler runner loop claims due tasks (once/interval/daily/weekly), dispatches generation/render executors, enforces no-reentry, syncs run states; once-tasks self-disable.

### Generation providers (plan Phase 10)

- Pluggable provider contract (validate/generate with guardrails: num_images ≤ 4, duration ≤ 10s, resolution whitelist; sanitized errors so keys never leak) in app/ai/providers.
- Real adapters: qwen-image via DashScope async tasks, Seedance via Volcano ARK content-generation tasks (pure payload builders unit-tested).
- Mock image/video providers synthesize media locally with ffmpeg so the whole pipeline runs offline.
- Credentials table (schema) + masked settings API and Settings UI for provider keys.
- Generation runner thread: submit→poll→download→register as generated asset + generated_assets row + job lifecycle; results are draggable timeline material immediately.
- AI Studio rebuilt: prompt composer, data-driven model pills, live-polling queue with result thumbnails.

### Transcript-driven editing (apply_transcript_edit)

- cut_clip_range operation removes a source range from a clip: split into left + ripple-closed right, edge cuts trim, full cuts delete — recorded as one invertible apply_transcript_edit operation (undo restores the original clip, redo re-applies).
- POST /sequences/{id}/clips/{clip_id}/cut-range; transcript panel segments carry a hover cut action wired through the projection's src range.

### Audio playback + waveforms

- Waveform cache (plan §8): mono peak buckets extracted with ffmpeg at import/export-registration, stored beside the asset, served via GET /api/assets/{id}/waveform.
- Audio-track clips render their sliced waveform (pure slicePeaks/downsample kernel, tested) as an SVG inside the clip.
- Monitor drives a hidden audio element in lockstep with the active audio-track clip (gain/mute honored); playback clock switched from rAF to interval so it survives occluded/background windows.

### Editing boost round 1 (parity work vs mibu-video)

- split_clip operation (cut-in-two at a source point, single invertible op) + S key / clip context menu at the playhead; ⌘D duplicate appends a copy at track end.
- set_track_state operation (mute/lock, undoable) with hover tools on track headers; muted video tracks drop their overlays from the render plan; locked tracks already reject drags.

### Editing boost round 2 (player, DnD, multi-select, speed/fade, transcript tools)

- Monitor is a real player: scrubber with hover thumb, frame stepping (←/→, Shift=10), skip to start/end, loop, 0.5–2x rate, master volume + mute, fullscreen, click-stage play toggle.
- Timeline: cross-track clip dragging with live lane preview; pool drags show a snap-aware dashed drop ghost and lane highlighting; shift/cmd-click multi-select + empty-lane marquee; Delete removes the selection.
- ripple_delete_clip operation (delete + shift same-track followers left, clamped, single undoable op) via Shift+Delete, context menu, and DELETE /clips/{id}/ripple.
- set_clip_speed operation (0.25–4x undoable) + speed presets in the Inspector; effective duration = source/speed flows through RenderPlan segments, FFmpeg setpts + chained atempo, timeline geometry, and Monitor source-time mapping/playbackRate.
- Fades from clip effects.fade_in/fade_out (clamped): fade/afade at segment edges in the executor, afade on audio overlays before adelay; fade inputs in the Inspector.
- cut_clip_ranges operation (batch source-range removal from one clip, merged + back-to-back, one undo step) powers the transcript tools: expandable word chips (token-level delete), amber-highlighted 口癖 with select-all, and 静音 gap detection (≥0.6s from token/segment timing) with per-gap and remove-all actions.
- Remaining parity queue: transitions, richer asset inspector.

### Filters + subtitles + chrome polish

- Filter presets (bw/warm/cool/vivid/fade) on clip effects: validated in RenderPlan, eq/hue chains in the executor, CSS-equivalent preview in the Monitor, preset row in the Inspector.
- Subtitle tracks: clips.asset_id nullable, text clips via insert_text_clip/set_clip_text (undoable), SRT burn-in on export, purple text clips on the timeline, Monitor overlay, Inspector textarea, 在播放头加字幕 toolbar action.
- Chrome: page headers removed app-wide (slim action toolbars instead), AI Studio 对话/生成 segmented control in the chat sidebar, visible timeline clip-action buttons, redesigned monitor transport (circular play, custom volume), hairline-only panel resizers, ChatGPT-grade assistant message typography, media-library covers fixed (missing auth token on thumbnail URLs).

### Professional color grading (mibu-video parity + beyond)

Per-clip color lives in `clip.effects.color`; the Inspector's 调色 tab and the Monitor's CSS/SVG preview both consume it, and it burns into FFmpeg on export.

- 16-slider primary grade (exposure/contrast/temperature/…): normalized [-1,1], mapped to eq/curves/hue/colortemperature/vibrance/colorbalance/unsharp/vignette in the executor.
- DaVinci-style tone curves (`colorCurves.ts`): Luma/R/G/B control points → `curves=` in export and an SVG `feComponentTransfer` in preview, both composing master∘channel (the real FFmpeg order); near-duplicate x-points de-duped at plan time so the vf chain can't be rejected. Channel-tabbed `CurveEditor` with drag/add/remove/reset.
- Color-grade presets (`colorPresets.ts`): six curated looks (Vivid/B&W/Warm/Cool/Cinematic/Fade) as pure data that fill the sliders + a signature curve; active preset highlighted by exact match; presets preserve an applied LUT.
- Per-clip color undo/redo (`useColorHistory.ts`): a dedicated stack, separate from the timeline's global undo, snapshotting color+filter before each edit (slider commit, preset, reset, curve gesture).
- 3D LUT: `.cube` upload/store/list/delete (`luts` table, per-workspace storage, header validator) + `lut3d` burn-in after the primary grade; `LutPicker` in the color panel wired to `effects.color.lut` (preview is export-only for LUTs).
- Scopes: histogram + waveform sampled from the current frame on an rAF loop, reflecting the grade via `ctx.filter`. A dedicated crossOrigin sampling video (cache-buster) reads untainted pixels without touching the main playback video.

### Plugin runtime (plan §19.6)

- Process-isolated execution: manifest `entry` script spawned per call with one JSON request on stdin / one JSON response on stdout ({ok, output|error}), 60s timeout, 1MB output cap, minimal env, cwd = plugin dir, entry path confined to the plugin directory.
- First version is pure-function tools only — plugins receive nothing but their input payload, so the permission/confirmation system cannot be bypassed; every call lands in plugin_invocations (running → succeeded/failed with error text).
- Required-input check from the tool's input_schema before spawning; MCP gains list_plugin_tools + invoke_plugin_tool so agents share the same registry.
- Plugins page: expandable tool cards generate a try-run form from input_schema (typed coercion for number/boolean/object), green/red result blocks, invocation history with expandable output/error.
- Runnable example plugin plugins/examples/text-toolkit (word_count, extract_hashtags); 8 runtime tests cover the protocol, crash/timeout/garbage-output/entry-escape paths and the API flow.

### Knowledge base (plan §18)

- SQLite FTS5 trigram baseline + optional tiers: dense vectors (Milvus Lite, RRF hybrid fusion) and an entity graph (Neo4j, config-gated) — all degrade gracefully when a tier is off; `/api/kb/status` reports which tiers are live.
- File conversion engines: markitdown (local default) or MinerU API, selected by config.
- Tiptap v3 note editor (StarterKit + official markdown extension + placeholder), markdown round-trip.

### Workflows + nesting + scheduler triggers (plan §12, Phase 13)

- `workflows.graph` JSON `{nodes, edges}` driven by a NODE_TYPES registry (start / llm / kb_search / plugin_tool / transcribe_asset / export_sequence / ai_generate / publish / condition / http_request / code / template / loops + the browser and composition nodes below) that simultaneously drives validation, the canvas UI and the agent's editing tools.
- Branch-aware engine: only nodes reachable via active edges run; condition nodes route true/false by `source_handle`; skipped nodes emit events. `{{node.key}}` interpolation between nodes. Code node = isolated python subprocess (20s, `-I`, PATH-only env).
- React Flow canvas: dual condition handles, cycle-checking `isValidConnection`, minimap, node inspector v2 (overlay panel, static/dynamic selects, upstream-variable chips, Dify-style `/` slash picker via mirror-div caret measurement).
- Per-workflow resident agent session (`external_key=workflow:<id>`) with memory; edits go through `update_workflow` behind confirmation cards; canvas auto-syncs on `updated_at` when not dirty.
- **Nesting redesign (ComfyUI + dify)**: `call_workflow` calls another saved workflow as a sub-flow (workflow-as-tool — map inputs, receive its declared outputs; runs as a child job that nests under the parent and cascades cancel; recursion + depth guarded, `MAX_NEST_DEPTH=8`); `output` node declares a workflow's named outputs (dify End-style) that a caller receives; `subgraph` wraps a group of nodes into a reusable, arbitrarily-nestable inline subgraph edited in a focused sub-canvas, seeded with `{{input.x}}`. Marquee-select on the canvas → **折叠为子图** collapses the selection into a subgraph node, auto-rewiring boundary references (`{{node.key}}` string refs and data edges) — pure transform in `frontend/src/features/workflows/collapse.ts`.
- **Unified engine**: subgraphs and loop bodies run on the same real parallel engine (`execute_graph`) as the top level — same parallel / condition / data-edge semantics, not a stripped-down sequential runner.
- Batch tab removed: "same workflow × N param rows" is now covered by workflows (loop_foreach / subgraph / call_workflow / multi-node).
- Scheduler = trigger + workflow: manual / once / interval / daily / weekly / **webhook** (per-task secret, public POST endpoint with constant-time compare, no-reentry 409).

### Publish + account matrix (plan §6.9, Phase 13)

- Platform registry with `executor` local (folder/webhook/mock) vs browser (douyin/bilibili/xiaohongshu/weixin-channels); per-platform `title_max` enforced at create; Chinese aliases.
- Full Electron publisher ported from mibu-video: per-account persistent session partitions, CDP file upload, adapters, foreground/background view management, cross-account concurrency with same-account serialization.
- Worker queue protocol (claim / report rich statuses / claim-check / mark-due / heartbeat) — see [PUBLISHING.md](PUBLISHING.md) for the protocol and the **hard constraints** learned the hard way.
- Account matrix moved out of the Publish page into the **浏览器池** tab (see below): binding badges, platform nickname, last-check time, login / recheck / enable / rename / delete; checking-deadlock self-heal. The Publish page now shows publish records + 新建发布 only.
- AI publish copy; publish workflow node; **`browser_upload` node** ("浏览器·上传文件") sets a file on a page's `<input type=file>` via CDP `DOM.setFileInputFiles` (no OS dialog) — takes an `asset_id` (e.g. `{{export_1.asset_id}}`) or a local `file_path`, the key primitive for publishing via workflow.

### Browser pool / persistent-login (BrowserProfile)

- Every persistent browser login is unified into one concept: `BrowserProfile` (DB table `browser_profiles`) = a reusable login identity = a persistent session partition + proxy + metadata. **发布账号 = 挂了平台的档案** (`publish_accounts.profile_id`); **通用档案 = 不挂平台**, reusable for any site.
- Migration by **composition, not merge**: `publish_accounts` keeps its table + gains `profile_id`; each publish account gets a profile that reuses its existing partition `persist:mibu-<accountId>` (logins preserved). Generic profiles use `persist:pool-<id>`.
- New **浏览器池** tab (`frontend/src/features/browser-pool/BrowserPoolView.tsx`, Boxes icon, between 工作流 and 定时任务); adding/managing accounts and generic profiles happens here.
- **Lease**: one active session per profile at a time (`domain/browser.open_session`). **Login**: both publish accounts and generic profiles log in via the same app-embedded WebContentsView with a "返回 Open Studio" button — not a separate OS window.
- **Reusable by workflows**: the `browser_open` node gained `session_mode: pool` + `profile_id` → runs RPA reusing a pool profile's login.
- **Reusable by the agent** behind an explicit-authorization gate: `browser_pool_list` (read-only discovery — id/name/platform/login-status, no cookies) and `browser_pool_open(profile_id)` (a confirmation-card tool: the agent can use no logged-in profile without the user approving a card that names the identity — 显式授权每会话). See [MCP.md](MCP.md).

### Task bus, notifications, cancellation

- Task center: kind-aware icons/labels, click-through deep links per kind, cancel button on active rows.
- `POST /api/jobs/{id}/cancel`: job → terminal, publish task → cancelled, workflow/batch stop at node boundaries.
- Notifications: per-user rows fanned out to workspace members (`team` type reserved for collaboration requests), unread badge + popover center, produced by publish settles / workflow failures / batch completion.

### Desktop shell + server switching

- Full-width topbar with mac traffic lights inside it; `is-desktop`/`is-mac`/`is-win` classes; drag regions.
- Local/team server picker on the **login screen** (must precede auth) and in Settings — health-probe before switch, force-connect fallback, reload to re-resolve `API_BASE`.

### 2026-07 wave: full UI rebuild + team invitations + editor interaction parity

- **Style system rebuilt**: every handwritten global class inlined as Tailwind v4 classes on JSX (`styles.css` 10.4k → ~40 lines of portal overrides); dual palettes redesigned (warm-paper light `#f6f4f0`+`#6a5cd8`, warm-sandalwood dark `#141218`+`#8a7bf0`, independently calibrated), `--radius: 8px` scale (sm6/md8/lg10/xl14), pill segmented controls, **no drop shadows anywhere** (hairline borders + surface steps), solid `--field` form fills, CVD-validated chart palettes.
- **Team membership is invitation-based**: admins invite by username (`workspace_invitations`), invitees accept/decline from actionable notification cards; four roles + per-permission overrides remain. Admin-created accounts removed.
- **Editor interaction parity with mibu-video**: pool→timeline drags on dnd-kit (native HTML5 DnD dead under Electron); transform-based clip drags with 200ms settle glide and animated insert-ripple parting; **two-tier snapping** (target-track edges beat playhead/cross-track candidates); true insert edits (a clip straddling the drop point splits, its tail ripples — move and pool-drop alike, undo/redo carries the split); vertical auto-scroll while dragging.
- **Import hardening**: duration-less MediaRecorder webm (camera/screen/mic) losslessly remuxed at import + startup backfill for legacy assets; recorder rejects empty capture (<2KB) with a retry prompt instead of importing dead files.
- **Login redesigned**: split-screen photo hero (`public/login-hero.jpg`, gradient fallback), labeled form fields, Terms of Service / Privacy Policy dialogs (`features/auth/legal.tsx`, zh/en) with an implicit-consent line on registration.
- **Global search (⌘K) fixed**: palette does its own CJK/pinyin/server matching so cmdk's value-filter is disabled, manual empty state waits out in-flight searches, controlled first-item highlight restores Enter, deep links retry at 80/300/800ms.
- **Long dynamic dropdowns are searchable** (shared Combobox): publish asset/account, batch & scheduler workflow pickers, dubbing target, workflow-node resource fields.
- **Publish**: demo/mock platform removed from the registry (folder/webhook + real browser platforms remain).
- **Workspace/project UX**: breadcrumb switcher always visible with a create-workspace entry; created workspaces/projects seed the query cache before navigation (kills the stale-list bounce-back); project creation jumps straight into its empty editor.

### 2026-07-28: preview↔export parity by contract, and a dead-code sweep

- **Scene contract** (`contracts/scene-cases.json`): the semantics preview and export must agree on
  literally — visible layers at t, z-order, base assignment — expressed as a language-neutral corpus
  that `backend/tests/test_scene_parity.py` and `sceneModel.parity.test.ts` both execute. A one-sided
  semantic change now turns both suites red. Rationale and the rejected alternative (方案 Y: canvas
  composites the export frames) are in [ADR-0004](adr/0004-preview-export-parity-by-contract.md).
- **Two real parity bugs the contract caught immediately**, each with a green-but-contradictory test
  on either side: a **muted upper video track** showed in preview and vanished from the export (the
  track header's mute is a speaker icon — audio only; picture stays, audio drops); an **empty bottom
  video track** was treated as the base by preview (demoting the real picture to an overlay and
  losing fill-mode framing) but not by export. Base is now the bottom-most track that actually
  carries picture, on both sides.
- **Colour is deliberately NOT in the contract**: ffmpeg is authoritative (`eq`/`curves`/`lut3d`),
  preview is a declared CSS/canvas approximation. Making canvas authoritative would delete tone
  curves and 3D LUT from exports. Text was already pixel-identical (export rasterises the app's own
  CSS through headless Chromium).
- **`code` node is now gated as host access, not content access**: it runs arbitrary Python on the
  backend host, so all four persist paths (create / import / patch / confirmation approval) require
  `ensure_instance_admin`. The scan recurses into subgraph and loop bodies — folding a `code` node
  into a subgraph would otherwise walk straight past the gate.
- **Dead code removed**: the unwired 方案 Y cluster (`OfflineFrameRenderer`, `OfflineVideoSource`,
  `frame_encoder`, the export-proxy builders and route), 8 `_migrate_*` functions predating the first
  public release, predecessor-project fallbacks (`.mibu-video` / `.mibu-new` data dirs, sibling-venv
  and Fish Speech probes), and the 30 Alembic migrations — never executed at runtime and drifted from
  `models.py` since 2026-07-23. Migrations that serve v0.1.0/v0.2.0 users are kept; the retirement
  rule is in ARCHITECTURE.md.
- **Two latent test-isolation defects fixed** (exposed, not caused, by the new tests): agent turns run
  in daemon threads that kept writing while `fresh_client()` rebuilt the schema, and `_wait_idle`
  returned in the gap between a turn ending and its queued successor starting. The parallel-branch
  test also stopped inferring concurrency from total wall-clock and now asserts that the two
  execution spans overlap.

## Next

- Precise preview ("render preview"): render a selected range through the real export pipeline so a
  user can see exact frames on demand — the industry answer (PR/DaVinci) to a fast-but-approximate
  live preview. Designed in ARCHITECTURE.md, not built.
- Transitions (转场) in the render plan and editor.
- Plugin write-path tools via jobs + confirmation cards; scoped API token injection per granted permission.
- Windows packaging + smoke test (mac done); app icon, code signing, auto-update.
- Split the oversized feature files (WorkflowsView 2.3k lines, EditorView 1.1k, Timeline 1k) along canvas/inspector/node-form seams.
- Publish adapter seam slices (see MAINTENANCE_HOTSPOTS.md).

## Frontend Rules

- Use TailwindCSS classes inline on JSX and local shadcn/ui components for all interactive controls; no handwritten global classes or shared class-string files.
- Do not use native browser dialogs such as `alert`, `confirm`, or `prompt`.
- Keep all user-visible copy behind the i18n preference layer.
- Preserve light and dark theme support for every new surface.
- Timeline math lives in `domain/timeline/geometry.ts` as tested pure functions; components never inline geometry.
- Server entities stay in React Query; Zustand holds only drafts and transient UI state.
- No drop shadows; radii on the 8px scale; segmented controls are pills; form fills use `--field`.
- Vertical stacks use grid/flex + `gap`, never `space-y` (Tailwind v4 puts it on the previous child's margin-bottom — a no-op for inline children like labels).
- Elements positioned by inline styles must not also carry Tailwind translate/inset classes (v4's standalone `translate` property composes with inline `transform`).
- Dynamic long-list dropdowns use the shared searchable Combobox; drag interactions use dnd-kit.
