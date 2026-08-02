"""插件自带的工作流节点。

**为什么不是一个通用的「插件工具」节点**:那个节点在画布上长得跟别人不一样 —— 别的节点把
参数摊在表单里,它只有一个 `input` 的 JSON 文本框,填错了要跑一次才知道。插件是这个应用里
唯一一处"能力由第三方提供"的地方,而它在工作流里的表达却比内置能力矮一头。

参照 ComfyUI 的自定义节点:**插件自己声明节点长什么样**,应用只规定必须遵守的形状 ——

    {
      "name": "fetch_one_video",
      "node": {
        "label": "抖音作品详情",
        "description": "按作品 id 取一条抖音作品的完整信息。",
        "config": {
          "aweme_id": {"type": "template", "required": true, "description": "作品 id"}
        },
        "outputs": ["title", "author", "digg_count"]
      }
    }

`config` 与 `outputs` 就是 NODE_TYPES 里那两个字段,同一套语义、同一个编辑器、同一份校验 ——
插件节点和内置节点在画布上没有区别,这正是这件事的目的。

**不声明 node 也能用**:`input_schema` 本身就是一份 JSON Schema,足够生成一张表单。所以
"插件工具自动就是一个像样的节点"是默认行为,`node` 只是想要更好的标签、更细的类型、或者把
输出拆成几个具名口子时才写。对 MCP 类插件尤其重要 —— 那边的清单是从服务现拉的,插件作者
根本没机会给每个工具写 node 块。

节点类型 id 是 `plugin.<插件id>.<工具名>`。带前缀是为了让**图文件**自解释:一个工作流导出到
别人机器上,少了插件时报的是"这个节点来自插件 X",而不是一句"未知节点类型"。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

PLUGIN_NODE_PREFIX = "plugin."

#: 插件节点在节点面板里的分组。与 NODE_CATEGORIES 的最后一项对齐。
PLUGIN_NODE_CATEGORY = "插件"

#: JSON Schema 的 type → 节点 config 的 type。
#:
#: 字符串映到 **template** 而不是 string:工作流里的字符串入参十有八九要引用上游输出
#: (`{{node.output}}`),template 那档在编辑器里会把可用变量列出来。纯字面量照样能填。
_SCHEMA_TYPES = {
    "string": "template",
    "number": "number",
    "integer": "number",
    "boolean": "boolean",
    "object": "object",
    "array": "object",
}


def node_type_id(plugin_id: str, tool_name: str) -> str:
    return f"{PLUGIN_NODE_PREFIX}{plugin_id}.{tool_name}"


def parse_node_type(node_type: str) -> tuple[str, str] | None:
    """`plugin.<插件id>.<工具名>` → (插件id, 工具名);不是插件节点返回 None。

    插件 id 里有点号(`dev.openstudio.tikhub`),所以按**最后一个**点切 —— 工具名是标识符,
    不含点。反过来按第一个点切会把插件 id 拆散。
    """
    if not node_type.startswith(PLUGIN_NODE_PREFIX):
        return None
    rest = node_type[len(PLUGIN_NODE_PREFIX) :]
    plugin_id, dot, tool_name = rest.rpartition(".")
    if not dot or not plugin_id or not tool_name:
        return None
    return plugin_id, tool_name


def _config_from_schema(schema: Any) -> dict[str, dict[str, Any]]:
    """JSON Schema → 节点 config 声明。"""
    if not isinstance(schema, dict):
        return {}
    properties = schema.get("properties")
    if not isinstance(properties, dict):
        return {}
    required = {key for key in (schema.get("required") or []) if isinstance(key, str)}
    config: dict[str, dict[str, Any]] = {}
    for key, spec in properties.items():
        if not isinstance(key, str):
            continue
        spec = spec if isinstance(spec, dict) else {}
        # 联合类型(["string","null"])取第一个非 null 的分支 —— 表单只能长一个样子。
        raw_type = spec.get("type")
        if isinstance(raw_type, list):
            raw_type = next((t for t in raw_type if t != "null"), "string")
        entry: dict[str, Any] = {"type": _SCHEMA_TYPES.get(str(raw_type), "template")}
        if key in required:
            entry["required"] = True
        if spec.get("description"):
            entry["description"] = str(spec["description"])
        enum = spec.get("enum")
        if isinstance(enum, list) and enum:
            entry["options"] = [str(value) for value in enum]
        config[key] = entry
    return config


def node_meta(tool: dict[str, Any]) -> dict[str, Any]:
    """一个插件工具的节点元数据,形状与 NODE_TYPES 的条目完全一致。

    插件写了 `node` 就用它的;没写就从 input_schema 生成。两者可以混着来 —— 只想改个标签的
    插件写一行 label 即可,config 仍然自动生成。
    """
    declared = tool.get("node") if isinstance(tool.get("node"), dict) else {}
    config = declared.get("config")
    if not isinstance(config, dict) or not config:
        config = _config_from_schema(tool.get("input_schema"))
    outputs = declared.get("outputs")
    if not isinstance(outputs, list) or not outputs:
        # 默认一个口子装整份返回。插件想拆成具名输出就自己声明 outputs。
        outputs = ["output"]
    label = str(declared.get("label") or tool.get("tool_name") or "")
    description = str(declared.get("description") or tool.get("description") or "")
    return {
        "label": label,
        # 面板上每行都有一句说明;插件没写就退到"来自哪个插件",总比空着强。
        "description": description or f"来自插件「{tool.get('plugin_name', '')}」的工具。",
        "category": PLUGIN_NODE_CATEGORY,
        "config": config,
        "outputs": [str(name) for name in outputs],
        # 前端据此在节点上标出处;也让"缺插件"的报错说得出是谁。
        "plugin_id": tool.get("plugin_id", ""),
        "plugin_name": tool.get("plugin_name", ""),
        "tool_name": tool.get("tool_name", ""),
    }


def plugin_node_types(db: Session) -> dict[str, dict[str, Any]]:
    """当前可用的插件节点类型。已启用 + 权限已授 + 凭据齐全的插件才在列。

    **这份注册表是动态的**,这正是它不能并进 NODE_TYPES 的原因:NODE_TYPES 是这份代码的
    常量(有测试钉着它和执行器一一对应),而插件装了什么是用户机器上的事实。
    """
    from app.domain.plugins.registry import list_enabled_plugin_tools

    return {
        node_type_id(tool["plugin_id"], tool["tool_name"]): node_meta(tool)
        for tool in list_enabled_plugin_tools(db)
    }


__all__ = [
    "PLUGIN_NODE_CATEGORY",
    "PLUGIN_NODE_PREFIX",
    "node_meta",
    "node_type_id",
    "parse_node_type",
    "plugin_node_types",
]
