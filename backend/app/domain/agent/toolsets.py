"""工具集:**这个应用 / 这个插件的工具是干嘛的**,给别的智能体看的一份高层目录(`GET /api/agent/toolsets`,
也在 `/api/agent/manifest` 里)。工具清单回答「能调什么」,工具集回答「这一组是干嘛的」。

清单版本 7 之前它叫 `skills`(`CORE_SKILLS`、`/api/agent/skills`)。改名是因为「技能」现在指智能体按需读的
做法(SKILL.md,见 ADR 0040 与 domain/agent/skills)—— 同一个词指两件事,写插件的人和模型都会读混。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.db.models import PluginInstance


CORE_TOOLSETS = [
    {
        "id": "mosael.assets",
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
        "id": "mosael.sequences",
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
        "id": "mosael.ai_generation",
        "name": "AI Generation",
        "description": "Create image and video generation jobs across configured providers, and optimize an image prompt for a target platform's conventions.",
        "source": "core",
        "tools": [
            {"name": "list_generation_models", "method": "GET", "path": "/api/generation/options"},
            {"name": "create_generation_job", "method": "POST", "path": "/api/generation/jobs"},
            {"name": "optimize_image_prompt", "method": "POST", "path": "/api/generation/optimize-prompt"},
        ],
        "permissions": ["generation:read", "generation:write"],
    },
    {
        "id": "mosael.scheduler",
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
        "id": "mosael.plugins",
        "name": "Plugins",
        "description": "Scan plugins, list enabled tools, and record plugin invocations.",
        "source": "core",
        "tools": [
            {"name": "scan_plugins", "method": "POST", "path": "/api/plugins/scan"},
            {"name": "list_plugin_tools", "method": "GET", "path": "/api/plugins/tools"},
            {"name": "invoke_plugin_tool", "method": "POST", "path": "/api/plugins/instances/{instance_id}/tools/{tool_name}/invoke"},
        ],
        "permissions": ["plugins:read", "plugins:write"],
    },
]


def list_agent_toolsets(db: Session, user_id: str | None = None) -> list[dict[str, Any]]:
    """核心工具集 + 每个**可用实例**贡献的工具集。

    实例(而不是包)是工具集的主人:同一个包的两次接入是两套凭据、两个端点,给别的智能体看的
    也该是两条 —— 「TikHub · 哔哩哔哩」和「TikHub · 抖音」能做的事不一样。
    """
    from app.domain.plugins import instances as inst
    from app.domain.plugins.tools import exposed

    toolsets = [dict(toolset) for toolset in CORE_TOOLSETS]
    by_instance: dict[str, list[dict[str, Any]]] = {}
    for tool in exposed(db, user_id):
        by_instance.setdefault(tool["instance_id"], []).append(
            {
                "name": tool["name"],
                "description": tool["description"],
                "instance_id": tool["instance_id"],
                "invoke_path": f"/api/plugins/instances/{tool['instance_id']}/tools/{tool['name']}/invoke",
                "input_schema": tool["input_schema"],
            }
        )
    for instance_id, tools in by_instance.items():
        instance = db.get(PluginInstance, instance_id)
        if instance is None:
            continue
        manifest = inst.manifest_for(db, instance)
        for toolset in manifest.toolsets:
            if not isinstance(toolset.get("id"), str):
                continue
            toolsets.append(
                {
                    "id": f"{instance.id}:{toolset['id']}",
                    "name": toolset.get("name", toolset["id"]),
                    "description": toolset.get("description", ""),
                    "source": f"plugin:{instance.package_id}",
                    "instance_name": instance.name,
                    "tools": tools,
                    "permissions": manifest.permissions,
                }
            )
    return toolsets
