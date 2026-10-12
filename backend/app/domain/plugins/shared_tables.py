"""插件回答里重复的大表只搬了一次(`shared_tables` + `x-shared-table`)—— 在这里展平回每一格。

一次回答的上限是 1MB(`runtime.MAX_OUTPUT_BYTES`),而 ComfyUI 一张工作流的工具带着好几张几百项的下拉表,而且
同一张表在图里每多一个节点就多一份:对着真机量,36 个工具的清单 1,055,758 字节,其中 58 万字节是重复的同一批表
(403 份、只有 77 张不同的表;维护者那台报 42 个工具)。插件因此把**重复的**表放在回答顶层一次、格子上指过去
(见 docs/PLUGIN_MANIFEST「一两张大表在一次回答里只搬一次」),而且**只在宿主说了收得下时才这么交**
(请求的 `accepts`,见 runtime)。

展平放在 `runtime._final_response` 里,而不是每个入口各做一次:一问一答和流式两条路共用那一段判读,再往下的
每一处 —— 存进 `plugin_instances.discovered_tools`、工作流节点的 config、画板、插件页「试一下」、发给智能体的
那一份 —— 看到的都是**展平之后**的形状,和插件逐格写全时一模一样:下拉照样是整张(ADR 0044 修订)。
"""

from __future__ import annotations

from typing import Any

from app.domain.plugins.errors import PluginDomainError

#: 插件在回答里说它共享了哪些表(见模块说明)。
TABLE_KEY = "shared_tables"
#: 格子上指过去的那一格。
REF_KEY = "x-shared-table"
#: 宿主在请求的 `accepts` 里说它收得下这个(插件据此决定要不要共享)。
ACCEPTS = "shared_tables"


def expand(output: dict[str, Any]) -> dict[str, Any]:
    """一份插件回答 → 每一格都带着整张表的那一份(`shared_tables` 收走)。没共享过的原样交回,不做深拷贝。

    指到一张没交上来的表是**插件交回的东西不对**:照实说,不收这一份 —— 收下的话那一格就没有可选值了,
    而表单要的是整张下拉。别悄悄留一个指不到的引用。
    """
    if TABLE_KEY not in output:
        return output
    tables = output.pop(TABLE_KEY)
    if not isinstance(tables, dict):
        raise PluginDomainError("pluginErr_sharedTablesBadShape", shape='{"<id>": [value, …]}')
    _inline(output, tables)
    return output


def _inline(node: Any, tables: dict[str, Any]) -> None:
    if isinstance(node, dict):
        name = node.pop(REF_KEY, None)
        if name is not None:
            values = tables.get(name) if isinstance(name, str) else None
            if not isinstance(values, list):
                raise PluginDomainError("pluginErr_sharedTableMissing", table=str(name)[:40])
            node["enum"] = values
        for child in node.values():
            _inline(child, tables)
    elif isinstance(node, list):
        for child in node:
            _inline(child, tables)


__all__ = ["ACCEPTS", "REF_KEY", "TABLE_KEY", "expand"]
