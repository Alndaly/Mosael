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
        # 「留空也能跑的专业旋钮」收进高级区,和内置节点同一套语义(NODE_TYPES 的 advanced)。
        # JSON Schema 没有这个概念,所以认 `x-advanced` 这个扩展键;直接写 `advanced` 也认 ——
        # 插件作者八成会先试后者,为一个拼写把人挡在门外不值得。
        if spec.get("x-advanced") is True or spec.get("advanced") is True:
            entry["advanced"] = True
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
    label = str(declared.get("label") or tool.get("label") or tool.get("name") or "")
    description = str(declared.get("description") or tool.get("description") or "")
    return {
        "label": label,
        # 面板上每行都有一句说明;插件没写就退到"来自哪个插件",总比空着强。
        "description": description or f"来自插件「{tool.get('instance_name', '')}」的工具。",
        "category": PLUGIN_NODE_CATEGORY,
        # 「用哪个连接」是节点的一个普通配置项,和别的字段走同一套表单与校验。
        "config": {
            "instance_id": {
                "type": "string",
                "description": "用哪个连接(同一个插件可以接多个)",
                "plugin_instances": True,
                # 只接了一个实例时留空即可 —— 正是「留空也能跑」,不该占第一屏。
                "advanced": True,
            },
            **config,
        },
        "outputs": [str(name) for name in outputs],
        # 前端据此在节点上标出处;也让"缺插件"的报错说得出是谁。
        "plugin_name": tool.get("instance_name", ""),
        "tool_name": tool.get("name", ""),
    }


def plugin_node_types(db: Session, user_id: str | None = None) -> dict[str, dict[str, Any]]:
    """当前可用的插件节点类型。可用实例(启用 + 配置齐 + 凭据齐 + 已授权)暴露的工具才在列。

    **这份注册表是动态的**,这正是它不能并进 NODE_TYPES 的原因:NODE_TYPES 是这份代码的
    常量(有测试钉着它和执行器一一对应),而装了什么插件是用户机器上的事实。

    **节点类型按包聚合,不按实例**:同一个包的两个实例(B站 / 抖音)提供的是同一批节点,
    选哪个实例是节点 config 里的一个字段。工作流会被导出到别的机器,而实例是本机事实 ——
    绑包的话,导出的图在别人机器上缺的是"连接"(可以现场建);绑实例的话缺的是"节点类型",
    图直接打不开。
    """
    from app.domain.plugins.tools import exposed

    out: dict[str, dict[str, Any]] = {}
    for tool in exposed(db, user_id):
        key = node_type_id(tool["package_id"], tool["name"])
        if key not in out:
            out[key] = node_meta(tool)
    return out


def instances_for_node(db: Session, node_type: str, user_id: str | None = None) -> list[dict[str, str]]:
    """这个节点类型可以用哪些实例。节点配置里的「连接」下拉读它。"""
    from app.domain.plugins.tools import exposed

    parsed = parse_node_type(node_type)
    if parsed is None:
        return []
    package_id, tool_name = parsed
    return [
        {"id": tool["instance_id"], "name": tool["instance_name"]}
        for tool in exposed(db, user_id)
        if tool["package_id"] == package_id and tool["name"] == tool_name
    ]


__all__ = [
    "PLUGIN_NODE_CATEGORY",
    "PLUGIN_NODE_PREFIX",
    "node_meta",
    "node_type_id",
    "parse_node_type",
    "plugin_node_types",
]
