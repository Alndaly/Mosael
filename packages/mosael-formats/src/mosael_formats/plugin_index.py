"""插件市场索引里的**一条**:由插件清单原文生成。

三份索引长同一个形状,都由这里生成:

- 发版产物里的 `registry.json`(应用里的插件市场默认读它)与官网上那一份 —— scripts/sync-plugin-registry.py;
- 社区服务的 `GET /api/community/v1/plugins/index.json`(应用里「社区」来源读它)。

**索引不手写。** 手写的话它和插件本身会漂:版本号改了索引没改、插件加了个权限索引还写着旧的那几条
—— 而用户在装之前看到的正是索引里那一份。
"""

from __future__ import annotations

from typing import Any

from mosael_formats.effects import plugin_tool_effects

#: 一条索引有哪些键。社区服务的测试拿它对官网那份 registry.json 的每一条。
ENTRY_KEYS = (
    "id",
    "name",
    "version",
    "summary",
    "description",
    "author",
    "author_url",
    "docs",
    "homepage",
    "download",
    "permissions",
    "runtime",
    "provides",
    "tools",
    "bundled",
)


def tool_effects(raw: dict[str, Any], tool: dict[str, Any]) -> str:
    """一个声明过的工具的后果:覆盖 > 声明 > 包上的 default_effects > external;只读的是 none。
    与桌面端 plugins.registry._market_effects 同一个算法(真正的规则在 plugin_tool_effects 里)。"""
    policy = raw.get("tools") or {}
    override = (policy.get("overrides") or {}).get(tool["name"]) or {}
    return plugin_tool_effects(
        read_only=override.get("read_only") is True or tool.get("read_only") is True,
        declared=override.get("effects") or tool.get("effects"),
        default=policy.get("default_effects"),
    )


def index_entry(raw: dict[str, Any], *, download: str, bundled: bool) -> dict[str, Any]:
    """一条索引。`download` 由调用方按产物给;随应用内置的插件给空串、`bundled=True`。"""
    toolsets = raw.get("toolsets") or []
    author = raw.get("author") if isinstance(raw.get("author"), dict) else {}
    return {
        "id": raw["id"],
        "name": raw.get("name", ""),
        "version": raw.get("version", ""),
        # 一句话说清它是干嘛的(清单的 summary,可按语言分;原样带过去,由读的一方挑语言)。卡片和详情页头先摆它。
        "summary": raw.get("summary") or "",
        # 描述取第一条工具集的说明 —— 那句话本来就是写给"这东西是干嘛的"的(顶层 description 见 ADR 0040 §8)。
        "description": (toolsets[0].get("description") if toolsets and isinstance(toolsets[0], dict) else "") or "",
        # 作者从清单来(清单里是 {name, url})。**author 仍是一个字符串** —— 已经装着的旧版本
        # 按字符串读它;改成对象的话,它们的市场里会显示一串 {'name': …}。主页另起一个键。
        "author": str(author.get("name") or ""),
        "author_url": str(author.get("url") or ""),
        # 在 Mosael 里怎么用的文档,可按语言分;原样带过去,由读的一方挑语言。
        "docs": raw.get("docs") or "",
        # 主页**只从清单来**,应用的插件页读的也是清单里这一个值 —— 两处一条规矩。
        "homepage": str(raw.get("homepage") or "").strip(),
        "download": download,
        # 权限**从清单来**:界面在装之前把它摊开给用户看,写错等于骗人。
        "permissions": [p for p in (raw.get("permissions") or []) if isinstance(p, str)],
        # 它是本机脚本还是一个 MCP server —— 后者的工具由 server 自己报,装之前列不出来。
        "runtime": str((raw.get("runtime") or {}).get("kind") or "process"),
        # 它能替 Mosael 做哪类事(公网直链…)。和工具清单一样是「装了能得到什么」。
        "provides": [p for p in (raw.get("provides") or []) if isinstance(p, str)],
        # 声明的工具:名字、显示名和说明(按语言分的原样带过去)。**不带入参 schema** ——
        # 市场里要回答的是"它能干什么",怎么调是装上之后的事,而 schema 会让索引胖一个数量级。
        # 每个工具带上它的后果:市场详情据此标出哪些工具智能体调用前会先问你。
        "tools": [
            {
                "name": str(tool["name"]),
                "label": tool.get("label") or "",
                "description": tool.get("description") or "",
                "effects": tool_effects(raw, tool),
            }
            for tool in ((raw.get("tools") or {}).get("declare") or [])
            if isinstance(tool, dict) and tool.get("name")
        ],
        "bundled": bundled,
    }


__all__ = ["ENTRY_KEYS", "index_entry", "tool_effects"]
