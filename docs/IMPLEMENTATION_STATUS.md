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
- Provider profiles (schema): multiple named provider accounts with vendor presets (DashScope/ARK/Kimi/MiniMax/OpenAI/compatible), base_url + default model, enable toggle; legacy credentials remain as fallback; Settings UI rebuilt around profiles. *(Superseded 2026-08-01: a profile is now a connection with many models; `default_model` is gone — see the 2026-08-01 entry.)*
- Asset analysis: images direct, videos frame-sampled (ffmpeg) into OpenAI-compatible multimodal chat — works with Kimi & MiniMax profiles; POST /assets/{id}/analyze + analyze_asset MCP tool; chat composer supports file attachments that land as assets and are referenced in the message for the agent.

### Agent host layer + Feishu binding

- Open Studio hosts a specialized external coding-agent (user decision — opencode-style, not a homegrown loop): agent_sessions/agent_messages (schema), pi sidecar adapter (Node embedding pi-agent-core; tools call back over REST with a minted service token; continuity via serialized adapter_state; specialized system prompt teaching the confirmation contract); single-flight turns, errors become assistant messages.
- Chat Workspace in AI Studio (对话/生成 tabs): sessions, bubble thread, thinking indicator, composer. Verified with a real agent turn calling list_assets.
- Feishu binding ported from the predecessor project: lark-oapi long-connection worker (one child process per bot), tenant-token send, message dedupe + mention stripping, chats map to agent sessions (external_key feishu:bot:chat) with capability-tier prompts; 扫码一键创建 via device-authorization grant + manual App ID/Secret; Settings section with QR, bot list, status, capability; autostart on app launch, cleanup on shutdown.

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

### Editing boost round 1 (parity work vs the predecessor project)

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

### Professional color grading (predecessor parity + beyond)

Per-clip color lives in `clip.effects.color`; the Inspector's 调色 tab and the Monitor's CSS/SVG preview both consume it, and it burns into FFmpeg on export.

- 16-slider primary grade (exposure/contrast/temperature/…): normalized [-1,1], mapped to eq/curves/hue/colortemperature/vibrance/colorbalance/unsharp/vignette in the executor.
- DaVinci-style tone curves (`colorCurves.ts`): Luma/R/G/B control points → `curves=` in export and an SVG `feComponentTransfer` in preview, both composing master∘channel (the real FFmpeg order); near-duplicate x-points de-duped at plan time so the vf chain can't be rejected. Channel-tabbed `CurveEditor` with drag/add/remove/reset.
- Color-grade presets (`colorPresets.ts`): six curated looks (Vivid/B&W/Warm/Cool/Cinematic/Fade) as pure data that fill the sliders + a signature curve; active preset highlighted by exact match; presets preserve an applied LUT.
- Per-clip color undo/redo (`useColorHistory.ts`): a dedicated stack, separate from the timeline's global undo, snapshotting color+filter before each edit (slider commit, preset, reset, curve gesture).
- 3D LUT: `.cube` upload/store/list/delete (`luts` table, per-workspace storage, header validator) + `lut3d` burn-in after the primary grade; `LutPicker` in the color panel wired to `effects.color.lut` (preview is export-only for LUTs).
- Scopes: histogram + waveform sampled from the current frame on an rAF loop, reflecting the grade via `ctx.filter`. A dedicated crossOrigin sampling video (cache-buster) reads untainted pixels without touching the main playback video.

### Plugin runtime (plan §19.6, rebuilt — see docs/adr/0005)

- **Three layers: package → instance → capability.** A package is what is on disk; an instance is
  one concrete hookup (config + credentials + name + enable switch), so one package can be
  connected many times (TikHub: one package, a dozen platform endpoints, a connection each);
  a capability is one tool that connection exposes, **opt-in per tool**. Enabling everything
  drowns the node palette and the agent's tool list, and a model picking from fifty names picks
  wrong more often.
- **Two plugin kinds.** A local script (`entry` → process-isolated: one JSON request on stdin, one
  JSON response on stdout, 60s timeout, 1MB output cap, minimal env, entry confined to the plugin
  dir), or a **declarative MCP service** (`kind: "mcp"`, stdio or http) whose tool list is pulled
  from the service rather than hand-copied into the manifest.
- Plugins get **their own** credentials injected, never Open Studio's — so they cannot route around
  the permission system or the confirmation cards. Every call lands in `plugin_invocations`.
- Plugin-declared **workflow nodes**: a plugin says what its node's form, inputs and outputs look
  like, instead of everything degrading into one generic "plugin node".
- Compatibility is handled by **migration, not read-time branching** (docs/adr/0006): old manifest
  filenames and shapes are rewritten in place on upgrade.
- Examples: `plugins/examples/text-toolkit` (local script), `tikhub` (MCP), `mcp-everything`.

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

- Platform registry holds **only login-bearing real platforms** (douyin/bilibili/xiaohongshu/weixin-channels), all browser-driven; per-platform `title_max` enforced at create; Chinese aliases. The old `executor` split (`local` = folder/webhook/mock) is gone — see the 2026-07-31 entry.
- Full Electron publisher ported from the predecessor project: per-account persistent session partitions, CDP file upload, adapters, foreground/background view management, cross-account concurrency with same-account serialization.
- Worker queue protocol (claim / report rich statuses / claim-check / mark-due / heartbeat) — see [PUBLISHING.md](PUBLISHING.md) for the protocol and the **hard constraints** learned the hard way.
- Account matrix moved out of the Publish page into the **浏览器池** tab (see below): binding badges, platform nickname, last-check time, login / recheck / enable / rename / delete; checking-deadlock self-heal. The Publish page now shows publish records + 新建发布 only.
- AI publish copy; publish workflow node; **`browser_upload` node** ("浏览器·上传文件") sets a file on a page's `<input type=file>` via CDP `DOM.setFileInputFiles` (no OS dialog) — takes an `asset_id` (e.g. `{{export_1.asset_id}}`) or a local `file_path`, the key primitive for publishing via workflow.

### Browser pool / persistent-login (BrowserProfile)

- Every persistent browser login is unified into one concept: `BrowserProfile` (DB table `browser_profiles`) = a reusable login identity = a persistent session partition + proxy + metadata. **发布账号 = 挂了平台的档案** (`publish_accounts.profile_id`); **通用档案 = 不挂平台**, reusable for any site.
- Migration by **composition, not merge**: `publish_accounts` keeps its table + gains `profile_id`; each publish account gets a profile that reuses its existing partition `persist:openstudio-<accountId>` (logins preserved). Generic profiles use `persist:pool-<id>`.
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
- **Editor interaction parity with the predecessor project**: pool→timeline drags on dnd-kit (native HTML5 DnD dead under Electron); transform-based clip drags with 200ms settle glide and animated insert-ripple parting; **two-tier snapping** (target-track edges beat playhead/cross-track candidates); true insert edits (a clip straddling the drop point splits, its tail ripples — move and pool-drop alike, undo/redo carries the split); vertical auto-scroll while dragging.
- **Import hardening**: duration-less MediaRecorder webm (camera/screen/mic) losslessly remuxed at import + startup backfill for legacy assets; recorder rejects empty capture (<2KB) with a retry prompt instead of importing dead files.
- **Login redesigned**: split-screen photo hero (`public/login-hero.jpg`, gradient fallback), labeled form fields, Terms of Service / Privacy Policy dialogs (`features/auth/legal.tsx`, zh/en) with an implicit-consent line on registration.
- **Global search (⌘K) fixed**: palette does its own CJK/pinyin/server matching so cmdk's value-filter is disabled, manual empty state waits out in-flight searches, controlled first-item highlight restores Enter, deep links retry at 80/300/800ms.
- **Long dynamic dropdowns are searchable** (shared Combobox): publish asset/account, batch & scheduler workflow pickers, dubbing target, workflow-node resource fields.
- **Publish**: demo/mock platform removed from the registry (folder/webhook removed later — see 2026-07-31).
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
  public release, predecessor-project fallbacks (old data dirs, sibling-venv
  and Fish Speech probes), and the 30 Alembic migrations — never executed at runtime and drifted from
  `models.py` since 2026-07-23. Migrations that serve v0.1.0/v0.2.0 users are kept; the retirement
  rule is in ARCHITECTURE.md.
- **Two latent test-isolation defects fixed** (exposed, not caused, by the new tests): agent turns run
  in daemon threads that kept writing while `fresh_client()` rebuilt the schema, and `_wait_idle`
  returned in the gap between a turn ending and its queued successor starting. The parallel-branch
  test also stopped inferring concurrency from total wall-clock and now asserts that the two
  execution spans overlap.

### 2026-08-01: providers ⇄ models split, token-aware context, thinking, subscription quota

- **A provider profile is a connection, not a model.** New `provider_models` table: each row carries
  its own `capability_ids`, `context_window`, `max_output_tokens`, `reasoning` / `vision` /
  `reasoning_effort` / `developer_role`, enabled flag and source (catalog | manual).
  `provider_profiles.default_model` / `capability_ids` / `model_overrides` are **deleted**, and
  `provider_defaults` now points at a model row. The old single-model-per-profile shape forced users
  to name profiles after models — the same key pasted five times — because one endpoint's chat model
  and image model could not appear in two capability sections. ~20 call sites of
  `profile.default_model` collapsed into `provider_models.model_id_for(db, profile, capability)`.
  Model lists merge configured rows with the vendor's live catalog; catalog-missing models stay usable
  and are just badged. Owner module is `domain/provider_models.py` (ratchet-enforced).
- **Model settings dialog**: capability chips first (they decide what else is relevant — an image model
  has no context window), context window with catalog / override / fallback provenance shown inline,
  and four compat switches behind an **Advanced** disclosure. Adding a model is one searchable
  Combobox that also accepts a hand-typed id (DashScope's catalog has 233 entries; a flat list is
  neither scrollable nor searchable).
- **Token-aware context compaction** (rewritten; `contextWindow` was previously never read — the old
  rule was a message count). Usage is anchored on the last assistant message carrying real provider
  usage, with only newer messages estimated at `CHARS_PER_TOKEN = 3.5`. Over `COMPACT_RATIO = 0.8` of
  the window, older turns are summarized by the model and the last `KEEP_RECENT = 8` kept; the split
  point backs up to a `user` message so no orphan `tool_result` survives. Summarization failure
  degrades to truncation but still reports what happened. Runs **between turns**, not in
  `transformContext` (which fires per LLM call inside tool loops).
- **Context readout + manual compaction in the UI**: a meter and a 「立即整理上下文」 button, both in the
  composer's session-settings popover (AI Studio and the workflow assistant share one component).
  Compaction lands in the timeline as a collapsed notice (messages moved out, tokens freed).
- **Thinking level** (off / low / medium / high) as a session setting, forwarded to pi as
  `thinkingLevel`; `thinking_start/delta/end` stream into the same timeline as tool calls (ordered),
  rendered as a collapsible block that auto-collapses when done. Off means "we don't ask for it" —
  models that think anyway (k3, DeepSeek reasoner) still have their thinking shown.
- **Subscription quota**, fetched on click only: six parsers (Anthropic / Codex / OpenRouter / Kimi /
  xAI / Copilot) in `domain/provider_quota.py`, surfaced in a per-connection popover. None of these
  endpoints is a documented public API, so polling them on a timer would both hit rate limits and rot
  silently.
- **OAuth tokens refresh themselves.** Refresh previously happened only on the chat path, so an
  overnight gap always showed 「令牌已过期」 in settings for a credential that would have healed on
  first use. Listing profiles now refreshes expired ones first (via pi's `models.getAuth` — the
  protocol stays in pi rather than being reimplemented six times in Python); only a *failed* refresh
  surfaces, in warning colour, as 「需重新授权」. Failures back off for 5 minutes.
- **Retry is shared by every AI call**, not just chat: `domain/ai_retry.RetryingClient` (an
  `httpx.Client` subclass retrying 429/5xx/RequestError in `send()` with exponential backoff + jitter)
  is used by 15 modules — rate limits apply to image, video, TTS and embedding just the same.
  The cap is configurable under Settings → AI runtime.
- **Composer rebuilt** across AI Studio and the workflow assistant: the row that used to carry eight
  equally-weighted controls now keeps only what's looked at every turn (mode, attachments, model,
  send); analysis mode, thinking level, the context meter and compaction moved into one shared
  session-settings popover.
- **Floating panels and canvas nodes get `Cmd/Ctrl + [ / ]`** to raise/lower z-order, with focus
  tracked on the capture phase (drag and resize both `stopPropagation`). Nodes structurally cannot
  outrank floating panels — React Flow's viewport `transform` creates its own stacking context.
- **Workflow edges** offer two shapes (bezier / smoothstep), persisted per user.

### 2026-08-16: publish matrix on real accounts, backend i18n, trajectory view, subtitle dubbing

- **Per-platform publish options** (`domain/publish.PLATFORM_OPTIONS`): visibility, YouTube's
  `made_for_kids`, Xiaohongshu's originality declaration — declared once, the form renders from the
  declaration. **B站 and 视频号 declare an empty set with a comment saying the control was looked for
  and is not there**; an option that silently does nothing is worse than a missing one. TikTok and
  YouTube publishing were driven end-to-end on real accounts (private / only-me posts), which is where
  most of the fixes below came from: `waitButtonEnabled` was being handed CSS selectors and silently
  answered "not ready" for ten minutes; YouTube's completion check matched the upload page itself and
  reported success in 3 ms; a disabled `ytcp-button` read as clickable.
- **The backend does its own i18n** (`core/i18n.py`): domain stores keys, the exit translates by
  `Accept-Language`. Job messages carry `message_key` + `message_params` **in columns**, because a job
  record outlives the request that wrote it — translating on write freezes the language at that moment,
  which was the actual bug. Four ratchets keep it from drifting back.
- **Type scale follows the screen**: 673 hardcoded font sizes collapsed into four `clamp()` tokens.
- **FunASR is one multilingual entry, not a Chinese one.** The catalogue had bound it to Chinese and
  then to two presets; both were wrong — the engine is multilingual, and *language picks the weights,
  not the engine*. Collapsed to a single 972 MB SenseVoice bundle (was a 2.2 GB Chinese set), warmup
  and transcribe now build the request through one shared function (they had drifted: warmup was
  re-downloading 2 GB of weights the other path never used).
- **Trajectory view for agent sessions** (`features/ai-studio/trace/`): three lanes (input / model /
  tools) over the whole session, a step ledger below, per-step payload / result / timing. Two
  projections — equal-width (needs no timestamps, always drawable) and real duration with idle
  compressed — because *not every record has an absolute time*, and inventing one would be a lie.
  Unknown is `null` everywhere, never `0`: "no usage events" and "spent nothing" are different facts.
  The backend gained the other half: a **system-prompt snapshot recorded only on turns where it
  changed** (cross-session memory and the task plan are interpolated into it, so it differs almost
  every turn), and context injection stored on the user message — it was being interpolated into the
  prompt and never persisted, so the trajectory showed a question the model never received.
- **Subtitle dubbing** (`audio/subtitle_dub.py`): per-cue and batch, landing on a dedicated track
  (`Track.role == "dub"`, migrated, backfilled by what is *on* the track — all-TTS clips and at least
  one, so BGM tracks and the empty remains of a failed run are not promoted). "Fit to cue length" uses
  the clip's own `speed` — the render already chains atempo — so it stays lossless and undoable.
  Bilingual cues ask which line to read: feeding both to TTS reads the source and then the translation,
  turning a 3-second cue into twelve.
- **F5-TTS: language belongs to the weights, not the engine** (`audio/f5_models.py`). Two constants had
  pinned the checkpoint, so "what languages does F5 support" got answered as "what languages does the
  engine support" — and the user heard gibberish. The runtime was always ready (`F5TTS(ckpt_file=…,
  vocab_file=…)`); it just had those two values nailed down. Ten languages are now a table; adding one
  is a row plus a download. Each model lands in its own directory because **every community repo names
  its vocab `vocab.txt`** — sharing a directory means the second download silently overwrites the
  first's vocab, and the only symptom is "it still reads it wrong".
- **A language guard in front of synthesis** (`audio/tts_language.py`): the engine does not error on a
  script it cannot read, it just produces gibberish and reports success. The test is writing-system
  only — kana / hangul / Cyrillic / Arabic / Devanagari are hard evidence; **Latin letters prove
  nothing**, so French, German, Spanish, Italian and Finnish can only be chosen explicitly. Refusing
  wrongly blocks a synthesis that would have worked, so anything unproven is let through.

### 2026-08-17: media from a link (yt-dlp), and two places where the UI was lying

- **Import media from a link** (`media/ytdlp.py` + `domain/assets/from_url.py`). Probe first, then
  download what was ticked: a link may be one video or a whole playlist — one real playlist probed
  back **186 items**. Single video ticks itself; a playlist starts with nothing ticked, because a
  default-select-all on hundreds of items is one misclick from tens of gigabytes. Audio/video is a
  fork **before** downloading, not an extraction after it. Landing goes through `register_file_asset`,
  the same path as upload / local register / render output, so thumbnails, waveform and duration
  probing come for free (verified: a 10-minute video lands with `duration=634.6s`, `has_waveform=True`).
- **Login state is borrowed from the browser pool**, not exported by hand: a new `cookies` browser
  action reads the whole jar from the profile's partition (**not filtered by url** — video sites serve
  media from a different domain, and page-domain cookies alone still 403) and returns Netscape lines
  for the backend to write as cookies.txt.
- Three YouTube facts, each of which cost a debugging round and is written down where it is used:
  1. the default player client is **403** now; `android` works but only returns low-res formats;
  2. with cookies, **pinning a client is wrong** — the same jar gives 360p when pinned to
     `web_safari/web/mweb`, and 33 formats up to 1440p when nothing is pinned. The pinned list was an
     empirical answer to the anonymous-403 problem, and applying it to the signed-in case overrides a
     judgement yt-dlp keeps updating;
  3. YouTube now gates streams behind a **JS challenge**; unsolved, the formats are stripped entirely
     and yt-dlp reports `Only images are available`. Solving it needs a JS runtime plus yt-dlp's
     solver script, which is fetched on demand (`remote_components: ejs:github`) — a deliberate
     "download and run remote code" call, documented at the constant.
- **Quality is a ceiling, and the steps are the ones this link actually has.** Probing a single video
  already returns `formats`; the picker is built from them, so a link that tops out at 360p does not
  offer 2160p. Unknown (playlist flat-probe) falls back to generic steps — there "unknown" is honest
  and "only these" would be invented.
- Two UI lies fixed on the way: `<SelectItem value="">` (radix treats the empty string as "nothing
  selected", so picking 「不用」 left the trigger blank — the same pattern had been written twice), and
  a CJK title with no spaces widening the whole dialog (`min-width: auto` on flex/grid children).
- **Time-range cutting was built and then removed** at the user's request. It never worked here
  anyway: cutting has ffmpeg open the media URL directly and seek, which is a different network path
  from the download — the stream yt-dlp pulls at 5 MB/s times out for ffmpeg.

### 2026-08-18: a turn that waited 8 seconds on optional metadata, and "已授权" reported as "需重新授权"

Two findings that started from one question — why `tests/test_agent_queue.py` failed only under
random ordering. The answer was not the queue at all. A thread dump at the timeout showed:

```
httpcore/_backends/sync.py:128 in read          ← blocked on a socket, via http_proxy
  app/ai/model_catalog.py:99 in fetch_models
  app/ai/agent/host.py:162 in resolve_chat_provider
  app/ai/agent/host.py:554 in _run_turn_thread
```

**Starting a turn was making a real network call.** `resolve_chat_provider` looked up the
endpoint's model catalog to get `context_window` — optional metadata that already falls back to
`None`, already has a conservative default downstream, and is already overridden by whatever the
user typed on the model row. With an unreachable endpoint that lookup blocks for the full
`_FETCH_TIMEOUT = 8`. In the suite, `_wait_idle`'s timeout is *also* 8 — two equal timeouts
racing, which is exactly why it failed probabilistically. In production it means every message
sits for 8 seconds before the agent starts, whenever the configured base_url is slow or wrong.

- `cached_models` / `cached_model` read the cache and **never** fetch on the caller's thread;
  a miss returns `None` (still unknown) and schedules a background refresh. `None` vs `[]` is
  load-bearing: "haven't asked yet" and "asked, endpoint lists nothing" pick different fallbacks.
- Failures are cached too (`_FAILURE_TTL_SECONDS = 60`). Without that, an unreachable endpoint
  was retried on *every* call, each paying the full 8 seconds.
- `fetch_models` stays blocking for the settings page's model picker — there the user is waiting
  on the result, so blocking is correct. `find_model` had no callers left and was deleted.
- The suite no longer reaches the network at all: two autouse fixtures in conftest. Agent tests
  went from 2–3 probabilistic failures in 85s to green in 37s; the full suite 365s → 270s.

Separately, from 「明明授权成功却显示需要再次授权」: `oauth_expired` was plain
`is_expired(credential)`, and the UI renders that as a red 「令牌刷新失败 · 需重新授权」.
Subscription access tokens expire every few hours by design and the backend already refreshes
them in the background — so merely opening the settings page inside that window produced a
warning that was **not true**, and would have resolved itself seconds later. "Expired, being
refreshed" and "cannot be refreshed, needs you" had been flattened into one boolean. The backend
already tracked the second one in `_refresh_failed_at` but never consulted it; `oauth_expired`
now requires both. The frontend comment already claimed this ("走到这里说明后端已经替它刷过且
没刷动") — it described intent the backend had not implemented.

### 2026-08-18: five things the agent could not reach

Reported as "缺少一些必须的工具,比如获取当前时间". The registry had 51 tools and each of these
was a thing the model could only guess at or quietly give up on:

- **`get_current_time`** — it has a knowledge cutoff and no other way to learn today's date,
  so naming a file by date, reading 「最近的素材」, or writing a date into a caption were all
  guesses. Returns local + UTC ISO, zone, offset, weekday, unix. An unrecognised zone
  **says so** instead of silently falling back to the machine's — 「按东京时间」 computed in
  the wrong zone looks completely normal in the output.
- **`get_transcript`** — the largest gap. `transcribe_asset` only *starts* the work; there
  was no way to read the result, so cutting by content, summarising a video, or locating a
  quote were impossible. Segments carry start/end, so one maps straight to an `edit_timeline`
  cut. Per-word tokens are dropped and the segment list is capped at 200 — with `truncated`
  reported, because "that's all of it" and "there's much more" are otherwise identical to a model.
- **`list_jobs`** — `get_job` needs an id, and when the user asks 「渲染好了吗」 nobody has one.
- **`list_workspaces`** — every tool's `workspace_id` falls back to *the first workspace*, and
  that fallback is invisible: a whole conversation can run against the wrong one with no sign.
- **`import_media_from_url`** — the yt-dlp import added in 0.18 existed only in the UI.

`scripts/sync-tool-docs.py` regenerated docs/MCP.md (51 → 56). Ratchets pin that each new tool
reaches both the MCP registry *and* `/api/agent/tools` (two hand-maintained lists drifting
silently is what that file exists to prevent), and that each description says *when* to use it —
a model that picks the wrong tool does not report a missing one, it improvises.

### 2026-08-18: installing engine runtimes on Windows — and an error that could not be diagnosed

Two reports from a Windows machine, both on the "download the model / runtime" button:

- transcription (FunASR/SenseVoice): `安装 funasr 运行依赖失败:1(n) ^^^^^ File "...\resources\python\Lib\zipfile\__init__.py", line 1068, in _read1 ... MemoryError: Unable to allocate output buffer.`
- voice cloning (F5-TTS): ``安装 f5-tts 运行依赖失败:note: run with `RUST_BACKTRACE=1` environment variable to display a backtrace``

**The second one is the real defect.** Both call sites ended the pip failure with
`(stderr or stdout)[-300:]` — cutting by *position*. pip's output ends with closing notes
(`note: …`, `[end of output]`) as a matter of course, so cutting from the tail lands on the one
part that carries no information; the actual verdict sits dozens of lines above. And the full
output survived nowhere — `run_logged` also keeps only the last 800 characters — so this report
could not be diagnosed at all. This is the *second* occurrence of the same shape:
`audio/voices.explain_worker_failure` had taken `[end of libtorchcodec loading traceback]`, a
separator line, as the cause.

New `core/pip_install.py` is now the only door to pip:

- **picks the verdict lines** (`ERROR:` / `error:` / a bare `XxxError:` closing a traceback)
  instead of taking the tail, ranking vague ones like `Failed building wheel for X` last rather
  than dropping them — the first version *did* drop them, and the ratchet caught it;
- translates known causes into a next step (out of memory, out of disk, needs a Rust/C++
  toolchain, no matching distribution, resolution conflict, network) and **says so plainly when it
  recognises nothing**, rather than inventing a reason;
- **writes the whole output to `~/.open-studio/logs/pip-*.log`** and names the file in the error.

Two root causes found behind the reports:

- **`--prefer-binary`.** `f5-tts` depends on `rjieba` (jieba's Rust implementation). rjieba ships
  an sdist for *every* release while the Windows + CPython 3.12 wheel is not on every one — pip
  picks by version number, lands on a release with no wheel, and compiles Rust in an environment
  that has no Rust. Not `--only-binary=:all:`: `transformers_stream_generator`, also in that tree,
  is sdist-only, so a blanket ban makes f5-tts uninstallable. What needs blocking is *compiling for
  the sake of a newer version number*, not compiling.
- **The MemoryError is the machine.** The traceback's caller line is `data = self._read1(n)` — the
  bounded branch, i.e. pip's 1 MB `copyfileobj` block. Failing to allocate 1 MB means it was out of
  memory, not that something asked for an absurd buffer. Nothing to fix in code; the message now
  says so and points at the page file.

Two more differences that existed only because the same logic had been written twice:
transcription never passed the configured **pip mirror** (cloning did — and the setting reads
「装引擎依赖时用的 pip 索引」), and neither passed a usable `--timeout`/`--retries` for a 2.5 GB
download over a mirror. Both call sites now go through the one installer, with a ratchet that
fails if any module outside it spells `"pip", "install"`. The venv's pip is also upgraded first:
it comes from `ensurepip`, frozen when the CPython bundle was built, and it is the program doing
the downloading and unpacking.

### 2026-08-16: costs that were priced but reported as unpriced, and publish records that were deleted

- **`summarize_usage` now returns `unpriced`** — which provider+model+capability failed to price and
  how many times. The home chart said 「暂无价格规则」 to a user who had configured nine of them; the
  truth was that none matched the model actually in use (rules are keyed by `profile.vendor`, and his
  `deepseek-v4-pro` rules hung off an `openai-compatible` profile while the calls ran on the
  `deepseek` one). A blanket denial is worse than no hint: it turns "add one rule" into "the feature
  is broken".
- **Deleting a published record now says what it costs.** 20 publish jobs from one debugging session
  (Xiaohongshu 7, TikTok 4, YouTube 4, Douyin 2, Channels 2, Bilibili 1) had their records deleted;
  the jobs, assets and accounts were all still there. There is exactly one `db.delete(task)` in the
  codebase and it is user-triggered — the path was simply too smooth. The confirmation said "produced
  files are untouched", which is about local files and neatly avoids the half that matters: the post
  stays up on the platform, and your own account of what you published is gone.

## Next

- Precise preview ("render preview"): render a selected range through the real export pipeline so a
  user can see exact frames on demand — the industry answer (PR/DaVinci) to a fast-but-approximate
  live preview. Designed in ARCHITECTURE.md, not built.
- Transitions (转场) in the render plan and editor.
- Plugin write-path tools via jobs + confirmation cards; scoped API token injection per granted permission.
- Windows packaging + smoke test (mac done); app icon, code signing, auto-update.
- Split the oversized feature files — `WorkflowsView.tsx` is now 3.2k lines and still growing
  (`WorkflowEditor` 1.1k, `NodeInspector` 885), `EditorView.tsx` 1.3k with 42 queries/mutations — along
  canvas / inspector / node-form seams. `Timeline.tsx` is large but cohesive (0 queries) and stays.
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

### 2026-07-31: system capability layer, Feishu-side approvals, and an executor split undone

- **`electron/system/`** — one module per capability behind a uniform `register(ctx)`; `main.cjs` only
  iterates. Tray + close-to-tray + launch-at-login (scheduled tasks live in the backend, which is a
  child process — closing the window used to stop them silently), `prevent-app-suspension` while jobs
  run, dock badge / taskbar progress, task-finished notifications suppressed while the window has
  focus, `openstudio://` (navigation only, whitelisted views), video/audio file associations, one
  global shortcut, and a single-instance lock. State is **pushed in** (`runningJobs`), never pulled:
  the layer knows nothing about the backend, which is what keeps it separately testable.
- **Confirmations can be approved from Feishu.** A turn started in Feishu gets its card posted back
  into that chat. Authorisation reuses `feishu_bindings` (open_id → account, still a workspace
  member) — seeing a card in a group does not confer the right to approve it. Both entries call one
  `authorize_and_approve`; they used to hand-copy the same checks, which on an authorisation path is
  a privilege escape waiting to happen.
- **folder/webhook publishing removed.** They were never accounts: no login identity, no platform —
  yet `create_account` unconditionally provisioned a `BrowserProfile`, so every one of them left a
  shell profile in the browser pool that could never hold a login. Briefly split into a `delivery`
  domain, then dropped entirely as low value. The `executor` field and its 9 branches (domain, worker,
  two frontend components) are deleted, not rewritten. Migration cleans up old rows and shell profiles.
- **Structural constraints are now tests** (`tests/test_import_layering.py`): lower layers never
  import `app.api`; the top-level import graph is acyclic; with lazy imports counted, only the
  SQLAlchemy `core.db ⇄ db.models` cycle is allowed. Cheap to state, easy to break by accident.
- **Frontend can finally test components.** vitest had no DOM environment, so all 24 test files were
  pure functions and every UI regression had to be checked by hand in a browser. jsdom +
  testing-library added; DOM tests opt in per file (`/** @vitest-environment jsdom */`) since vitest 4
  dropped `environmentMatchGlobs`. Caveat worth knowing: exit-animation bugs (content clearing while
  the dialog is still on screen) are **invisible** in jsdom — Radix unmounts immediately without
  animation, so those still need a real browser.
- **Sidecar bundle smoke test** (`agent-sidecar/test/bundle.smoke.mjs`, wired into release CI): drives
  the built artifact over stdio and demands *positive* evidence it reached the network. Added after
  pi-ai 0.82 shipped a module layout whose `.lazy` entrypoint, once bundled, left `ModelsImpl`
  undefined — every turn failed with `is not a constructor` while types and unit tests stayed green.
  Fix was the entrypoint (`@earendil-works/pi-ai/compat`, which is in the package's `sideEffects`
  allowlist), not the version.
- **Dependencies current across the board**: Electron 43, TypeScript 7, Vite 8, mcp 2.0 (`FastMCP` →
  `MCPServer`, `inputSchema` → `input_schema`), pi 0.83, Astro 7 / Starlight 0.41 for the docs site.

## Structural constraints added in 0.8.0

These are **ratchet tests** — allowlists that may only shrink. Each exists because the drift it
prevents already happened once, silently.

- `test_agent_workflow_parity.py` — every workflow node type has a matching agent tool, or a written
  reason it does not need one. Without it the agent silently lacked capabilities the canvas had, and
  a model that hits a missing tool does not say "I have no tool for this" — it improvises one
  (it once used `browser_wait` on impossible text as a sleep, burning 22s and reporting success).
- `test_mcp_tool_payloads.py` — every tool is called once against a live backend and must not be
  rejected on **payload shape**. `translate_text` shipped posting `{text,target,source}` at an
  endpoint wanting `{texts,target_lang}`: a 422 on every single call.
- `test_undo_registry.py` — every recorded sequence operation registers an inverse. When one did not,
  undo silently **skipped it and reverted an older edit** instead — 200, no error, the wrong thing gone.
- `test_chat_single_implementation.py` — only one module may build a `/chat/completions` request.
  Eight copies had drifted apart on retry, key redaction, empty-key handling and usage reporting.
- `test_usage_single_entry.py` — only `domain/usage.py` may call `record_usage`; every billable
  capability has a recorded path. This one found a seventh gap (podcast) that the human list missed.
- `test_tool_docs_in_sync.py` — the tool table in docs/MCP.md is generated, not hand-written. It had
  drifted to listing 15 of 54.
- `buttonPending.test.ts` — a `<Button>` that fires a request must show `loading`, not just `disabled`.
