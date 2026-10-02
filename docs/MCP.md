# Mosael 智能体工具

智能体(AI Studio、飞书、子智能体)能用的工具清单。工具返回稳定的产品摘要,不暴露内部表结构。

**只在后端进程内运行**:sidecar 经 `GET /api/agent/tools` 发现工具、经 `POST /api/agent/tools/{name}` 调用。
不再作为独立的 MCP(stdio)服务对外提供 —— 那要求工具体经 HTTP 回连后端,而进程内这条路本不需要。
注册表在 `backend/mcp_server.py`(名字是历史遗留):每个工具的 `@tool(effect=...)` 声明它做了什么,
工具体正在逐个改成直接调领域用例。

## Tools

<!-- BEGIN generated: tools -->

共 **100** 个工具,其中 **29** 个走确认卡、**1** 个停下来等用户作答。

| 工具 | 门控 | 说明 |
| --- | --- | --- |
| `analyze_asset` | 直接执行 | Analyze an EXISTING image/video media asset with a multimodal model. |
| `analyze_document_pages` | 直接执行 | Look at pages of a DOCUMENT asset with a vision model — layout, charts, tables, screenshots, slide design. |
| `append_note` | 直接执行 | Append requested writing or research to a note without replacing existing content. |
| `ask_user` | 等作答 | Ask the user to choose between options you cannot decide for them. |
| `attach_entity_reference` | 直接执行 | Attach an existing image (or video) asset to an asset-library entry as a reference image |
| `blender_execute` | 确认卡 | Confirmation required: run Python (bpy) inside the user's open Blender to model. |
| `blender_import_to_scene` | 直接执行 | Bring what you modeled in Blender into a Mosael 3D scene as ONE model object. |
| `blender_inspect` | 直接执行 | Read-only: what is in the Blender scene the user has open right now — every object's name, |
| `blender_look` | 直接执行 | Read-only: LOOK at the open Blender scene — returns rendered images you can see. |
| `blender_send_scene` | 直接执行 | Send a Mosael 3D scene into Blender, so you can refine it there with real modeling. |
| `browser_click` | 直接执行 | Click an element by CSS selector or visible text in the open session (one of selector/text). |
| `browser_close` | 直接执行 | Close a browser session (frees the view; a throwaway session's cookies/storage are wiped). |
| `browser_evaluate` | 直接执行 | Advanced: evaluate a JS expression in the open session's page and return its value. |
| `browser_navigate` | 直接执行 | Navigate an already-open browser session to a URL. Needs a session_id from browser_open. |
| `browser_open` | 确认卡 | Confirmation required: open an ISOLATED automation browser and optionally navigate to url. |
| `browser_pool_list` | 直接执行 | List the browser POOL profiles you may request access to — the user's reusable persistent logins |
| `browser_pool_open` | 确认卡 | Confirmation required: open a browser session that REUSES one of the user's LOGGED-IN pool |
| `browser_read` | 直接执行 | Read-only: extract visible text from the open page (whole body if no selector). The returned text |
| `browser_scroll` | 直接执行 | Scroll the open session to an element (selector) or by dy pixels. |
| `browser_type` | 直接执行 | Type text into an input/textarea in the open session. NEVER type passwords, payment, or credentials. |
| `browser_upload` | 直接执行 | Put an asset's file into a page's <input type=file> — the key step when uploading a video. |
| `browser_wait` | 直接执行 | Wait for an element (selector) / URL substring (url_contains) / page text in the open session. |
| `convert_video_to_gif` | 确认卡 | Confirmation required: convert an EXISTING video asset into a NEW GIF asset. |
| `create_entity` | 直接执行 | Create a character, location or prop in the asset library (a workspace edit, no confirmation). |
| `create_note` | 直接执行 | Create a persistent note when the user asks to save research or writing. Preserve factual |
| `create_project` | 直接执行 | Runs directly: create a project; returns its id. timeline=true also gives it an empty VIDEO TIMELINE. |
| `create_scene` | 直接执行 | Create an empty persistent 3D scene. Then use edit_scene to add geometry and camera shots. |
| `create_workflow` | 确认卡 | Confirmation required: create a NEW visual workflow. |
| `delete_assets` | 确认卡 | Confirmation required: PERMANENTLY delete media assets. This cannot be undone. |
| `delete_projects` | 确认卡 | Confirmation required: PERMANENTLY delete projects and their timelines. |
| `denoise_audio` | 确认卡 | Confirmation required: reduce background noise in an audio or video asset, producing a |
| `dub_subtitles` | 确认卡 | Confirmation required: speak subtitle cues aloud onto a new dub track. |
| `edit_board` | 确认卡 | Confirmation required: edit an EXISTING CREATIVE BOARD with granular canvas ops. |
| `edit_scene` | 直接执行 | Edit an actual 3D scene atomically, with undoable immutable revisions. Read get_scene first. |
| `edit_timeline` | 确认卡 | Confirmation required: propose edits to a VIDEO TIMELINE (ids from inspect_sequence). |
| `edit_workflow` | 确认卡 | Confirmation required: edit an EXISTING VISUAL WORKFLOW with granular graph ops. |
| `fetch_url` | 直接执行 | Read-only: fetch one public web page as readable text. |
| `forget` | 直接执行 | Runs directly: delete one memory entry. |
| `generate_audio` | 确认卡 | Confirmation required: generate a NEW spoken-audio asset from text. |
| `generate_image` | 确认卡 | Confirmation required: generate or edit an image asset. |
| `generate_podcast` | 确认卡 | Confirmation required: generate a NEW two-speaker podcast/dialogue audio asset. |
| `generate_sound` | 确认卡 | Confirmation required: generate a NEW music / sound asset — a song (with vocals), background |
| `generate_video` | 确认卡 | Confirmation required: generate a NEW video asset from a text prompt. |
| `get_answer` | 直接执行 | Read what the user picked for an ask_user question (or whether they skipped). |
| `get_board` | 直接执行 | Read-only: inspect one CREATIVE BOARD canvas in full. |
| `get_confirmation` | 直接执行 | Read-only: poll one confirmation card by confirmation_id. |
| `get_current_time` | 直接执行 | Read-only: what time is it right now, on the machine running this studio. |
| `get_entity` | 直接执行 | Read-only: one asset from the asset library — its description, prompt descriptor, reference |
| `get_job` | 直接执行 | Read-only: poll one background job (transcription, render, generation) by id. |
| `get_scene` | 直接执行 | Read the current editable 3D scene, objects, materials, camera shots and revision. |
| `get_transcript` | 直接执行 | Read-only: read the transcript/subtitles of an asset — timed segments with speakers. |
| `get_workflow` | 直接执行 | Read-only: inspect one VISUAL WORKFLOW graph in full. |
| `http_request` | 确认卡 | Confirmation required: call an external HTTP API (POST/PUT/PATCH/DELETE). |
| `import_from_url` | 确认卡 | Confirmation required: download a video (kind=audio: its audio) from a web link into the media library. |
| `import_media_from_url` | 直接执行 | Runs directly: download a video or audio from a link into the asset library. |
| `inspect_sequence` | 直接执行 | Read-only: a VIDEO TIMELINE's tracks and clips — the ids, times and revision edit_timeline needs. |
| `list_agent_sessions` | 直接执行 | Runs directly: list the agent sessions in this workspace (id, title, status). |
| `list_assets` | 直接执行 | Read-only: list media assets in a workspace (id, name, kind, source, duration). |
| `list_board_producers` | 直接执行 | Read-only: list what content items on a creative board can DO — their abilities and slot generators. |
| `list_boards` | 直接执行 | Read-only: list CREATIVE BOARDS (infinite canvases) in a workspace. |
| `list_entities` | 直接执行 | Read-only: list the asset library — the named CHARACTERS, LOCATIONS and PROPS of this workspace. |
| `list_generation_models` | 直接执行 | List the AI generation engines available to generate_image / generate_video / generate_sound. |
| `list_jobs` | 直接执行 | Read-only: list recent background jobs (renders, transcriptions, generations, imports). |
| `list_memories` | 直接执行 | Read-only: list what you already remember in this workspace. |
| `list_projects` | 直接执行 | Read-only: list video projects in a workspace (id, name, active_sequence_id). |
| `list_provider_models` | 直接执行 | List the AI connections and models this user has actually configured, by capability. |
| `list_publish_accounts` | 直接执行 | Read-only: the platform accounts already logged in, for publish_asset. |
| `list_publish_tasks` | 直接执行 | Read-only: recent publish tasks, newest first, with what was published where. |
| `list_scene_models` | 直接执行 | Read-only: the imported 3D models available in this workspace, with id, name, format and size. |
| `list_scenes` | 直接执行 | List persistent 3D scenes in the workspace, with object and shot counts. |
| `list_speech_engines` | 直接执行 | Read-only: the speech engines generate_audio / dub_subtitles can speak with, and their voices. |
| `list_workflow_node_types` | 直接执行 | Read-only: list allowed workflow node types, or inspect one type in full. |
| `list_workflows` | 直接执行 | Read-only: list VISUAL WORKFLOWS in a workspace. |
| `list_workspaces` | 直接执行 | Read-only: list the workspaces this user has, newest first. |
| `notify_agent_session` | 直接执行 | Runs directly: send a message to ANOTHER agent session (@-mention style). |
| `notify_workspace` | 直接执行 | Runs directly: push an in-app notification to the workspace members. |
| `open_view` | 直接执行 | Take the user to a page in Mosael — optionally to one specific record. |
| `publish_asset` | 确认卡 | Confirmation required: publish an asset to a platform with a logged-in account. |
| `read_document` | 直接执行 | Read-only: read an imported DOCUMENT asset (PDF, Word, PowerPoint, Excel, CSV, Markdown, text, web page, EPUB). |
| `read_note` | 直接执行 | Read a note with its source references and immutable revision. Cite citation_url after |
| `remember` | 直接执行 | Runs directly: save a durable fact or convention to cross-session memory. |
| `render_scene_references` | 直接执行 | Render blockout references of one shot of a 3D scene and save them as assets: |
| `render_sequence` | 确认卡 | Confirmation required: export an existing VIDEO TIMELINE sequence to mp4. |
| `reparse_document` | 确认卡 | Confirmation required: parse a DOCUMENT asset again with a named parser — "本地解析" (local) or a |
| `run_board_item` | 确认卡 | Run an ABILITY of a content item on a creative board (or its slot generator / 3D render), as if the user pressed it. |
| `run_code` | 确认卡 | Confirmation required: run a short Python snippet in an ISOLATED sandbox and return `output`. |
| `run_host_code` | 确认卡 | Confirmation required: run Python directly on the user's computer, NOT isolated. |
| `run_workflow` | 确认卡 | Confirmation required: execute an EXISTING visual workflow. |
| `search_notes` | 直接执行 | Search workspace notes by title, body and tags, including Chinese. Returns snippets, |
| `separate_audio` | 确认卡 | Confirmation required: split an audio or video asset into a voice stem and a |
| `sleep` | 直接执行 | Runs directly: pause for a few seconds before the next step. |
| `split_image_grid` | 确认卡 | Confirmation required: split an EXISTING grid image (a 3x3 sticker sheet, a 2x2 storyboard) into NEW images. |
| `transcribe_asset` | 直接执行 | Runs directly: run speech-to-text on an audio/video asset; returns the job. |
| `translate_text` | 直接执行 | Runs directly: translate text into a target language. |
| `update_asset` | 直接执行 | Runs directly: rename an asset and/or move it into a project. |
| `update_asset_tags` | 直接执行 | Runs directly: replace an EXISTING media asset's tag list. |
| `update_plan` | 直接执行 | Runs directly: publish/refresh your task plan for the current conversation. |
| `update_workflow` | 确认卡 | Confirmation required: rename a workflow or replace its ENTIRE graph. |
| `view_scene` | 直接执行 | Read-only: LOOK at a 3D scene — returns rendered images you can see. Free, local, ~1 s per view. |
| `web_search` | 直接执行 | Read-only: search the public web for up-to-date external information. |

<!-- END generated: tools -->

上面这张表**由 `scripts/sync-tool-docs.py` 从注册表生成**,不要手改 —— 手写清单会腐烂,
而且没有任何信号:这份文档一度只列了 54 个里的 15 个,缺的恰恰是后来加的那批(浏览器、记忆、
通知)。`tests/test_tool_docs_in_sync.py` 钉住它与代码一致。

表里的「等作答」是 `ask_user`：它不是「直接执行」的一种,这次调用会**停在那里等用户挑**。
和确认卡是同一个形状、两张不同的表(`agent_questions` / `tool_confirmations`):确认卡问「这件事
能不能做」、可以被「本会话始终允许」自动批准,而「你要哪一个」自动回答等于让模型自己编一个。
**怎么等由 manifest 上的标记驱动、各 runtime 自己生成**,所以工具描述里不写等法 —— 应用自己
那条(sidecar)阻塞轮询,直连 MCP 的客户端按回包 `message` 里的协议自己轮询 `get_answer`。
超时结局相反:确认卡超时 = 那个动作没有发生(抛错);选择卡超时 = 用户还没顾上,答案仍会由回执
送回这次对话,所以如实回一句「还没答」,并明确拦住「再问一遍」。

表里的「直接执行」只表示**不需要确认卡**，不是 AI 的 `direct` execution surface。以
`analyze_asset` 为例：普通、未绑定智能体会话的请求独立选择后端 `direct` 分析模型；AI Studio
工具回连则从 service token 的 `agent_session_id` 继承当前会话模型，API Key 仍走 `direct`，
订阅/OAuth 走无工具 `gateway`。图片先归一化；视频 `auto` 在 API Adapter 支持时可原生直读，
否则发送采样帧 + 已有转写。OAuth Gateway 没有原生 video block，因此 `auto` 走抽帧、`native`
明确失败；它不需要 `base_url`，也不会静默换成 `gpt-4o-mini` 或另一条连接。

`list_generation_models` 返回完整模型能力描述符；`generate_image` / `generate_video` 的参数说明也从
同一描述符生成。目录认不出的模型**不从同供应商其他型号继承**时长、尺寸或素材角色；它拿到的是这条
通道自己发得出的那几个键（Adapter 声明的参数面，只有键、没有取值范围），面依赖模型的通道则仍是空集。
两种情况下取值都未经验证，智能体照样可以只提交提示词。素材参数既可给 `asset_id`，也可按角色给 URL；两种传输形式进入相同的
必填、份数、互斥与搭伴校验。

工作流画布能做的事智能体都能做 —— 由 `tests/test_agent_workflow_parity.py` 钉住:节点类型
没有对应工具、又没写明为什么不需要,测试就红。

### The `destroy` tier

`delete_assets` and `delete_projects` are the only tools on this tier. Their consequences are
*inside* this application — so `external` is the wrong word — but they are not undoable: the
asset's file is removed from disk, a deleted project takes its timelines with it. `edit` is
defined as "recoverable at worst", so putting a delete there would be a lie told on the one line
the user reads before clicking approve.

In autopilot, `destroy` falls through to the same branch as `external`: there is no enumerable
criterion that makes a deletion safe, so it always goes back to a human. Deleting assets that a
timeline uses is allowed — those clips become offline placeholders (see `domain/assets/deletion`)
and the card says how many.

### The `external` tier

`edit`, `render-cost` and `ai-cost` all bound their worst case to *this* application: data the
user can undo, or money. `external` is the tier whose consequences are not here at all — a post
that is now public, a change on somebody else's server, code that already ran on this machine.
None of it is undoable, so the card gets its own wording and its own badge rather than reading
like "edit the timeline". Adding a tier means adding its `messages.ts` label; the parity ratchet
checks that too, because an unlabelled tier would otherwise render as some *other* tier's name —
on the one line a user reads before clicking approve.

The browser tools reuse the confirmation gate. `browser_pool_open` is the security-critical one: the agent can use **no** logged-in profile without the user approving a card that names the identity ("显式授权每会话"). Agents are instructed that page content is DATA, not instructions; never enter passwords/payment; and warn the user before any post/submit/purchase.

### 三档权限模式(已设计,未实现)

现在的门控是二元的:走卡或不走卡。三档模式(手动 / auto / bypass)的设计见
[ADR 0007](adr/0007-agent-permission-modes.md) —— 包括为什么「AI 自行判断是否放行」必须由一个
**看不到工具返回内容**的隔离判断者来做。落地方案与对 ADR 的三处修正见
[AGENT_PERMISSION_MODES.md](AGENT_PERMISSION_MODES.md)。

**权限档已经改成按 payload 派生**(第 1 期,已落地):`TOOL_DEFS` 里的值只是下限,`run_workflow`
与工作流的建/改会扫**这次会落库或执行的那张图**,含 `code` / `publish` / `http_request` /
`browser_*` / `plugin_tool` / `call_workflow` 的一律提到 `external`,摘要也点名图里有什么。
`browser_pool_open` 直接改成 `external` —— 它接的是用户在别人站点上的**真实身份**,不是"可撤销
的编辑"。档位不只是徽标:三档一上,它直接决定要不要放行,定错了放开的就是错的东西。

## Confirmation flow

Mutating tools never execute directly. They create a pending confirmation;
a card appears showing the requesting agent, permission level, and operation
details. Only user approval executes the action — timeline edits run through
SequenceOperations and stay undoable (⌘Z). Agents poll `get_confirmation` until
the status is terminal; `result` then carries the new revision or job id.

### Where the card appears — and who may approve it

Two entry points, one implementation:

| Entry | Identity comes from |
| --- | --- |
| Desktop UI (`POST /confirmations/{id}/approve`) | bearer token |
| **Feishu interactive card** | the clicker's `open_id`, resolved through the account binding |

A turn started from Feishu gets its card posted back into that same Feishu chat, so the
approval happens where the request was made rather than forcing a switch to the desktop app.

Authorisation reuses the existing account model — it is **not** a second scheme. The clicker
must already be bound to a Mosael account (`feishu_bindings`) **and still be a member of
the workspace**. Seeing the card in a group chat does not confer the right to approve it.
Binding is keyed by `open_id`, never `user_id` — mixing the two silently rejects people who did
bind.

Both entries call `domain/agent/confirmations.authorize_and_approve` / `authorize_and_reject`.
Identity resolution belongs to the entry; "may this person approve, and what happens when they
do" has exactly one implementation. It used to be hand-copied on both sides, which meant a
fourth check added to the HTTP route would silently not apply to the Feishu path — on an
authorisation path that is a privilege escape. `tests/test_feishu_card_confirmation.py` pins
this by stubbing the shared function and asserting both entries go through it.

Feishu cards need two developer-console settings (subscribe to `card.action.trigger`; enable
Interactive Card; then republish). Neither is settable via API, so one-click bot creation cannot
do it for you. When they are missing the send fails with `200340` and the backend degrades to a
plain-text notice that says which switches to flip — it does not fail silently.

<!-- BEGIN generated: timeline-ops -->

`edit_timeline` 认 **27** 种算子(`?` 是可选参数;`*` 是默认带上同一链接组的片段,`linked: false` 只动点名的这一段):

- `insert_clip(track_id, asset_id, timeline_start, src_out, src_in?, ripple?, speed?)`
- `move_clip*(clip_id, timeline_start, track_id?, ripple?)`
- `move_clips_batch*(moves:[{clip_id, timeline_start, track_id?}])`
- `trim_clip*(clip_id, timeline_start, src_in, src_out)`
- `split_clip*(clip_id, src_time)`
- `delete_clip*(clip_id)`
- `ripple_delete_clip*(clip_id, all_tracks?) — closes the gap; all_tracks = every unlocked track`
- `cut_clip_range*(clip_id, src_start, src_end) — rest closes up`
- `cut_clip_ranges_batch*(cuts:[{clip_id, ranges:[{src_start, src_end}]}]) — one entry per clip`
- `duplicate_clips(clip_ids, timeline_start?, track_id?) — keeps spacing; default: right after the originals; overwrites what it lands on`
- `add_track(track_kind?:video|audio|subtitle, index?) — index 0 = top row; default: video top, others bottom`
- `remove_track(track_id, with_clips?)`
- `set_track_state(track_id, muted?, solo?, duck?, locked?, hidden?)`
- `detach_clip_audio(clip_id)`
- `replace_clip_media(clip_ids, asset_id) — keeps position, length and settings`
- `set_clip_effects(clip_id, effects)`
- `set_clip_transform(clip_id, transform) — scale/x/y/rotation/opacity`
- `set_clip_speed*(clip_id, speed, ripple?) — 0.25–4; ripple: later clips follow`
- `set_clip_gain(clip_id, gain?, muted?) — omitted = unchanged`
- `set_sequence_reframe(width, height, fill_mode?:cover|contain|blur)`
- `insert_text_clip(track_id, text, timeline_start, duration) — a subtitle cue`
- `generate_subtitles(track_id, cues:[{text, timeline_start, duration}])`
- `set_clip_text(clip_id, text)`
- `set_clip_texts_batch(texts:[{clip_id, text}])`
- `set_subtitle_style(style) — font_size/color/bg_color/bg_opacity/position`
- `undo(expected_revision?) — refused if the revision moved`
- `redo(expected_revision?) — refused if the revision moved`

这一份从 `domain/sequences/op_args` 的入参模型生成 —— 智能体看到的说明、开卡时的参数校验都是它(见 test_timeline_ops_have_one_list、test_edit_timeline_args)。

<!-- END generated: timeline-ops -->

All tools default to the first workspace when `workspace_id` is omitted.
`inspect_sequence` accepts either `sequence_id` or `project_id` (most recent
sequence).

## Roadmap

Scheduler tools (`create_scheduled_task` …) join the confirmation flow next.
