from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Plugin
from app.domain.plugins import plugin_permissions_granted


CORE_SKILLS = [
    {
        "id": "mibu.assets",
        "name": "Assets",
        "description": "Import, list, and inspect media assets.",
        "source": "core",
        "tools": [
            {"name": "list_assets", "method": "GET", "path": "/api/assets"},
            {"name": "import_asset", "method": "POST", "path": "/api/assets/import"},
        ],
        "permissions": ["assets:read", "assets:write"],
    },
    {
        "id": "mibu.sequences",
        "name": "Sequences",
        "description": "Create timelines and apply edit operations.",
        "source": "core",
        "tools": [
            {"name": "create_sequence", "method": "POST", "path": "/api/sequences"},
            {"name": "inspect_sequence", "method": "GET", "path": "/api/sequences/{sequence_id}"},
            {"name": "insert_clip", "method": "POST", "path": "/api/sequences/{sequence_id}/clips"},
            {"name": "undo", "method": "POST", "path": "/api/sequences/{sequence_id}/undo"},
            {"name": "redo", "method": "POST", "path": "/api/sequences/{sequence_id}/redo"},
            {"name": "export_sequence", "method": "POST", "path": "/api/sequences/{sequence_id}/export"},
        ],
        "permissions": ["sequence:read", "sequence:write"],
    },
    {
        "id": "mibu.ai_generation",
        "name": "AI Generation",
        "description": "Create image and video generation jobs across configured providers, and optimize an image prompt for a target platform's conventions.",
        "source": "core",
        "tools": [
            {"name": "list_generation_models", "method": "GET", "path": "/api/generation/models"},
            {"name": "create_generation_job", "method": "POST", "path": "/api/generation/jobs"},
            {"name": "optimize_image_prompt", "method": "POST", "path": "/api/generation/optimize-prompt"},
        ],
        "permissions": ["generation:read", "generation:write"],
    },
    {
        "id": "mibu.scheduler",
        "name": "Scheduler",
        "description": "Create scheduled tasks and run them on demand.",
        "source": "core",
        "tools": [
            {"name": "list_scheduled_tasks", "method": "GET", "path": "/api/scheduled-tasks"},
            {"name": "run_scheduled_task", "method": "POST", "path": "/api/scheduled-tasks/{task_id}/run"},
        ],
        "permissions": ["scheduler:read", "scheduler:write"],
    },
    {
        "id": "mibu.plugins",
        "name": "Plugins",
        "description": "Scan plugins, list enabled tools, and record plugin invocations.",
        "source": "core",
        "tools": [
            {"name": "scan_plugins", "method": "POST", "path": "/api/plugins/scan"},
            {"name": "list_plugin_tools", "method": "GET", "path": "/api/plugins/tools"},
            {"name": "invoke_plugin_tool", "method": "POST", "path": "/api/plugins/{plugin_id}/tools/{tool_name}/invoke"},
        ],
        "permissions": ["plugins:read", "plugins:write"],
    },
]


def list_agent_skills(db: Session) -> list[dict[str, Any]]:
    skills = [dict(skill) for skill in CORE_SKILLS]
    plugins = db.scalars(select(Plugin).where(Plugin.enabled.is_(True)).order_by(Plugin.name)).all()
    for plugin in plugins:
        if not plugin_permissions_granted(db, plugin):
            continue
        permissions = plugin.manifest.get("permissions", [])
        tools = [
            {
                "name": tool.get("name"),
                "description": tool.get("description", ""),
                "plugin_id": plugin.id,
                "invoke_path": f"/api/plugins/{plugin.id}/tools/{tool.get('name')}/invoke",
                "input_schema": tool.get("input_schema", {"type": "object"}),
            }
            for tool in plugin.manifest.get("tools", [])
            if isinstance(tool, dict) and isinstance(tool.get("name"), str)
        ]
        for skill in plugin.manifest.get("skills", []):
            if not isinstance(skill, dict) or not isinstance(skill.get("id"), str):
                continue
            skills.append(
                {
                    "id": f"{plugin.id}:{skill['id']}",
                    "name": skill.get("name", skill["id"]),
                    "description": skill.get("description", ""),
                    "source": f"plugin:{plugin.id}",
                    "tools": tools,
                    "permissions": permissions,
                }
            )
    return skills
