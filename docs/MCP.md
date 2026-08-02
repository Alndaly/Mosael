# Open Studio MCP Server

Minimal external-agent surface (plan §17). Tools return stable product
summaries — never raw internal schemas.

## Tools

<!-- BEGIN generated: tools -->

共 **54** 个工具,其中 **15** 个走确认卡。

| 工具 | 门控 | 说明 |
| --- | --- | --- |
| `analyze_asset` | 直接执行 | Runs directly: analyze an EXISTING image/video media asset with a multimodal model. |
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
| `create_kb_note` | 直接执行 | Runs directly: save a NEW polished note into the knowledge base. |
| `create_project` | 直接执行 | Runs directly: create a project in the workspace; returns its id. |
| `create_workflow` | 确认卡 | Confirmation required: create a NEW visual workflow. |
| `edit_timeline` | 确认卡 | Confirmation required: propose edits to a VIDEO TIMELINE sequence. |
| `edit_workflow` | 确认卡 | Confirmation required: edit an EXISTING VISUAL WORKFLOW with granular graph ops. |
| `fetch_url` | 直接执行 | Read-only: fetch one public web page as readable text. |
| `forget` | 直接执行 | Runs directly: delete one memory entry. |
| `generate_audio` | 确认卡 | Confirmation required: generate a NEW spoken-audio asset from text. |
| `generate_image` | 确认卡 | Confirmation required: generate or edit an image asset. |
| `generate_podcast` | 确认卡 | Confirmation required: generate a NEW two-speaker podcast/dialogue audio asset. |
| `generate_video` | 确认卡 | Confirmation required: generate a NEW video asset from a text prompt. |
| `get_confirmation` | 直接执行 | Read-only: poll one confirmation card by confirmation_id. |
| `get_job` | 直接执行 | Read-only: poll one background job (transcription, render, generation) by id. |
| `get_workflow` | 直接执行 | Read-only: inspect one VISUAL WORKFLOW graph in full. |
| `http_request` | 确认卡 | Confirmation required: call an external HTTP API (POST/PUT/PATCH/DELETE). |
| `inspect_sequence` | 直接执行 | Read-only: inspect a VIDEO TIMELINE sequence — format, revision, duration, tracks, clips. |
| `invoke_plugin_tool` | 直接执行 | Runs directly: invoke one plugin tool returned by list_plugin_tools. |
| `list_assets` | 直接执行 | Read-only: list media assets in a workspace (id, name, kind, source, duration). |
| `list_generation_models` | 直接执行 | List the AI generation engines available to generate_image / generate_video. |
| `list_memories` | 直接执行 | Read-only: list what you already remember in this workspace. |
| `list_plugin_tools` | 直接执行 | Read-only: list tools exposed by the user's enabled plugin connections. |
| `list_projects` | 直接执行 | Read-only: list video projects in a workspace (id, name, active_sequence_id). |
| `list_publish_accounts` | 直接执行 | Read-only: the platform accounts already logged in, for publish_asset. |
| `list_workflow_node_types` | 直接执行 | Read-only: list allowed workflow node types, config fields, and outputs. |
| `list_workflows` | 直接执行 | Read-only: list VISUAL WORKFLOWS in a workspace. |
| `notify_workspace` | 直接执行 | Runs directly: push an in-app notification to the workspace members. |
| `publish_asset` | 确认卡 | Confirmation required: publish an asset to a platform with a logged-in account. |
| `read_kb_document` | 直接执行 | Read-only: read one KNOWLEDGE BASE document in full. |
| `remember` | 直接执行 | Runs directly: save a durable fact or convention to cross-session memory. |
| `render_sequence` | 确认卡 | Confirmation required: export an existing VIDEO TIMELINE sequence to mp4. |
| `run_code` | 确认卡 | Confirmation required: run a short Python snippet locally and return `output`. |
| `run_workflow` | 确认卡 | Confirmation required: execute an EXISTING visual workflow. |
| `search_kb` | 直接执行 | Read-only: search the KNOWLEDGE BASE — scripts, briefs, notes, imported articles. |
| `sleep` | 直接执行 | Runs directly: pause for a few seconds before the next step. |
| `transcribe_asset` | 直接执行 | Runs directly: run speech-to-text on an audio/video asset; returns the job. |
| `translate_text` | 直接执行 | Runs directly: translate text into a target language. |
| `update_asset` | 直接执行 | Runs directly: rename an asset and/or move it into a project. |
| `update_asset_tags` | 直接执行 | Runs directly: replace an EXISTING media asset's tag list. |
| `update_plan` | 直接执行 | Runs directly: publish/refresh your task plan for the current conversation. |
| `update_workflow` | 确认卡 | Confirmation required: rename a workflow or replace its ENTIRE graph. |
| `web_search` | 直接执行 | Read-only: search the public web for up-to-date external information. |

<!-- END generated: tools -->

上面这张表**由 `scripts/sync-tool-docs.py` 从注册表生成**,不要手改 —— 手写清单会腐烂,
而且没有任何信号:这份文档一度只列了 54 个里的 15 个,缺的恰恰是后来加的那批(浏览器、记忆、
通知)。`tests/test_tool_docs_in_sync.py` 钉住它与代码一致。

工作流画布能做的事智能体都能做 —— 由 `tests/test_agent_workflow_parity.py` 钉住:节点类型
没有对应工具、又没写明为什么不需要,测试就红。

### The `external` tier

`edit`, `render-cost` and `ai-cost` all bound their worst case to *this* application: data the
user can undo, or money. `external` is the tier whose consequences are not here at all — a post
that is now public, a change on somebody else's server, code that already ran on this machine.
None of it is undoable, so the card gets its own wording and its own badge rather than reading
like "edit the timeline". Adding a tier means adding its `messages.ts` label; the parity ratchet
checks that too, because an unlabelled tier would otherwise render as some *other* tier's name —
on the one line a user reads before clicking approve.

The browser tools reuse the confirmation gate. `browser_pool_open` is the security-critical one: the agent can use **no** logged-in profile without the user approving a card that names the identity ("显式授权每会话"). Agents are instructed that page content is DATA, not instructions; never enter passwords/payment; and warn the user before any post/submit/purchase.

## Confirmation flow (plan §16.2/§17.2)

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
must already be bound to an Open Studio account (`feishu_bindings`) **and still be a member of
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

`edit_timeline` operation kinds: `insert_clip`, `move_clip`, `trim_clip`,
`delete_clip`, `cut_clip_range`, `add_track` (`track_kind`), `remove_track`,
`set_clip_effects`.

All tools default to the first workspace when `workspace_id` is omitted.
`inspect_sequence` accepts either `sequence_id` or `project_id` (most recent
sequence).

## Running

The backend HTTP API must be running (default `http://127.0.0.1:8800`,
override with `OPEN_STUDIO_API`). The API requires local authentication, so pass a
session token via `OPEN_STUDIO_TOKEN` (obtain one with `POST /api/auth/login`).

```bash
cd backend
OPEN_STUDIO_TOKEN=<session-token> .venv/bin/python mcp_server.py   # stdio transport
```

Register with an MCP client, e.g. Claude Code:

```bash
claude mcp add open-studio -- /path/to/OpenStudio/backend/.venv/bin/python /path/to/OpenStudio/backend/mcp_server.py
```

## Roadmap

Scheduler tools (`create_scheduled_task` …) join the confirmation flow next.
