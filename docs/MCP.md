# Mibu MCP Server

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

## Confirmation flow (plan §16.2/§17.2)

Mutating tools never execute directly. They create a pending confirmation;
a card appears in the Mibu UI showing the requesting agent, permission level,
and operation details. Only user approval executes the action — timeline
edits run through SequenceOperations and stay undoable (⌘Z). Agents poll
`get_confirmation` until the status is terminal; `result` then carries the
new revision or job id.

`edit_timeline` operation kinds: `insert_clip`, `move_clip`, `trim_clip`,
`delete_clip`, `cut_clip_range`, `add_track` (`track_kind`), `remove_track`,
`set_clip_effects`.

All tools default to the first workspace when `workspace_id` is omitted.
`inspect_sequence` accepts either `sequence_id` or `project_id` (most recent
sequence).

## Running

The backend HTTP API must be running (default `http://127.0.0.1:8800`,
override with `MIBU_API`). The API requires local authentication, so pass a
session token via `MIBU_TOKEN` (obtain one with `POST /api/auth/login`).

```bash
cd backend
MIBU_TOKEN=<session-token> .venv/bin/python mcp_server.py   # stdio transport
```

Register with an MCP client, e.g. Claude Code:

```bash
claude mcp add mibu -- /path/to/mibu-new/backend/.venv/bin/python /path/to/mibu-new/backend/mcp_server.py
```

## Roadmap

Scheduler tools (`create_scheduled_task` …) join the confirmation flow next,
followed by publish tools.
