# Plugin Manifest

Mibu plugins are local directories under `~/.mibu-video/plugins/<plugin-folder>`.
Each plugin must contain `mibu.plugin.json` or `plugin.json`.

## Minimal Example

```json
{
  "id": "dev.caption-helper",
  "name": "Caption Helper",
  "version": "0.1.0",
  "permissions": ["assets:read", "sequence:write"],
  "skills": [
    {
      "id": "caption_assets",
      "description": "Create captions for selected media."
    }
  ],
  "tools": [
    {
      "name": "caption_asset",
      "description": "Generate captions for an asset.",
      "input_schema": {
        "type": "object",
        "properties": {
          "asset_id": { "type": "string" }
        },
        "required": ["asset_id"]
      }
    }
  ]
}
```

## Fields

- `id`: Stable unique plugin id.
- `name`: Display name.
- `version`: Plugin version.
- `permissions`: Declared access needs. The app will use this for user approval and sandboxing.
- `skills`: High-level abilities exposed to other agents.
- `tools`: Callable tool descriptors. `input_schema` should be JSON Schema.

The current runtime scans manifests, lets users enable plugins, grants declared permissions, aggregates enabled and approved tools, and records invocations. Actual sandboxed execution adapters come next.

Permissions are deny-by-default. A plugin can be enabled while still unapproved; in that state its tools are hidden from `/api/plugins/tools` and plugin skills are hidden from `/api/agent/skills`.

## Agent Integration

- `GET /api/agent/manifest`: app-level agent manifest with OpenAPI URL and skills.
- `GET /api/agent/skills`: core skills plus enabled plugin skills.
- `GET /api/plugins/tools`: enabled plugin tool descriptors only.
- `GET /api/plugins/{plugin_id}/permissions`: declared permission grants.
- `PATCH /api/plugins/{plugin_id}/permissions`: update permission grants.
- `POST /api/plugins/{plugin_id}/tools/{tool_name}/invoke`: records a plugin invocation.
