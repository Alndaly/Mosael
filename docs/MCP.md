# Mibu MCP Server

Minimal external-agent surface (plan §17). Tools return stable product
summaries — never raw internal schemas.

## Tools

| Tool | Kind | Description |
| --- | --- | --- |
| `list_projects` | readonly | Projects in a workspace (id, name, active sequence) |
| `list_assets` | readonly | Assets with kind, source, and duration |
| `inspect_sequence` | readonly | Timeline summary: format, revision, duration, tracks, clips |

All tools default to the first workspace when `workspace_id` is omitted.
`inspect_sequence` accepts either `sequence_id` or `project_id` (most recent
sequence).

## Running

The backend HTTP API must be running (default `http://127.0.0.1:8800`,
override with `MIBU_API`).

```bash
cd backend
.venv/bin/python mcp_server.py     # stdio transport
```

Register with an MCP client, e.g. Claude Code:

```bash
claude mcp add mibu -- /path/to/mibu-new/backend/.venv/bin/python /path/to/mibu-new/backend/mcp_server.py
```

## Roadmap

Mutating tools (`edit_timeline`, `render_sequence`, `generate_image`,
scheduler tools) arrive with the confirmation-card flow and permission
levels per plan §17.2/§17.4.
