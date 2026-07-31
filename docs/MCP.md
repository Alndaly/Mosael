# Open Studio MCP Server

Minimal external-agent surface (plan §17). Tools return stable product
summaries — never raw internal schemas.

## Tools

| Tool | Permission | Description |
| --- | --- | --- |
| `list_projects` | readonly | Projects in a workspace (id, name, active sequence) |
| `list_assets` | readonly | Assets with kind, source, and duration |
| `inspect_sequence` | readonly | Timeline summary: format, revision, duration, tracks, clips |
| `edit_timeline` | edit | Propose a batch of timeline operations — **requires user confirmation** |
| `render_sequence` | render-cost | Propose an mp4 export — requires confirmation; result carries job id |
| `generate_image` | ai-cost | Propose image generation — requires confirmation |
| `generate_video` | ai-cost | Propose video generation — requires confirmation |
| `get_confirmation` | readonly | Poll a confirmation: pending → executed/rejected/failed |
| `browser_open` | edit | Open an **isolated, throwaway** automation browser (cannot see the user's logins) — **requires confirmation**; returns a `session_id` the other `browser_*` tools drive |
| `browser_pool_list` | readonly | List browser-**pool** profiles the agent may request (id / name / platform / login status) — **no cookies or credentials exposed** |
| `browser_pool_open` | edit | Open a session **reusing one of the user's logged-in pool profiles** — **requires confirmation** on a card that names that identity (explicit per-session authorization); returns a `session_id` |

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

Scheduler tools (`create_scheduled_task` …) join the confirmation flow next,
followed by publish tools.
