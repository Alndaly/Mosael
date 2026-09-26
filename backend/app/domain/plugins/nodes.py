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

from app.domain.plugins.errors import PluginDomainError
from app.domain.plugins.inputs import ASSET_FORMAT
from app.domain.plugins.manifest import text_of

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

    插件 id 里有点号(`dev.mosael.tikhub`),所以按**最后一个**点切 —— 工具名是标识符,
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
        # 界面上叫什么:JSON Schema 的 `title`(可以按语言分)。不写就由节点目录按键名给一个可读名。
        if spec.get("title"):
            entry["label"] = text_of(spec["title"])
        # 插件用 `format: asset` 声明「这是一份素材」(运行时据此换成本地路径,见 inputs)。
        # 类型跟着声明走,不靠字段名碰运气:字段不叫 asset_id 时,命名约定认不出它,
        # 工作流里就拿不到素材选择器。`x-media` 说是哪一种素材(image / video / audio),选择器只列那一种。
        items = spec.get("items") if isinstance(spec.get("items"), dict) else {}
        if spec.get("format") == ASSET_FORMAT:
            entry["data_type"] = "asset"
        elif raw_type == "array" and items.get("format") == ASSET_FORMAT:
            # 一串素材:给能挑好几份的选择器,不是一个让人手写 `["…"]` 的 JSON 框
            entry = {**entry, "type": "asset_list", "data_type": "asset"}
            items_media = items.get("x-media")
            if isinstance(items_media, str):
                entry["media"] = items_media
        media = spec.get("x-media")
        if isinstance(media, str) and media in ("image", "video", "audio"):
            entry["media"] = media
        if spec.get("description"):
            entry["description"] = text_of(spec["description"])
        enum = spec.get("enum")
        if isinstance(enum, list) and enum:
            entry["options"] = [str(value) for value in enum]
        elif raw_type == "boolean":
            # 开关给「是 / 否」下拉(选项名由节点目录按语言翻);留空 = 不设
            entry["options"] = ["true", "false"]
        # 默认值当占位提示(告诉用户「留空会用什么」),不替他填
        default = spec.get("default")
        if isinstance(default, bool):
            entry["default"] = "true" if default else "false"
        elif isinstance(default, (str, int, float)) and str(default) != "":
            entry["default"] = str(default)
        if spec.get("x-multiline") is True and entry["type"] == "template":
            entry["multiline"] = True
        # 「留空也能跑的专业旋钮」收进高级区,和内置节点同一套语义(NODE_TYPES 的 advanced)。
        # JSON Schema 没有这个概念,所以认 `x-advanced` 这个扩展键;直接写 `advanced` 也认 ——
        # 插件作者八成会先试后者,为一个拼写把人挡在门外不值得。
        if spec.get("x-advanced") is True or spec.get("advanced") is True:
            entry["advanced"] = True
        config[key] = entry
    return config


def _readable(entry: Any) -> dict[str, Any]:
    """插件自己声明的一条 config,把其中给人看的字段本地化。其余原样透传。"""
    if not isinstance(entry, dict):
        return {}
    readable = dict(entry)
    #: 和从 input_schema 生成的那条同一个认法(见 _config_from_schema):`format: asset` 就是素材字段。
    #: 自己写 node.config 的插件不该因此丢掉素材选择器、画板上接不到上游的图片。
    if readable.get("format") == ASSET_FORMAT and not readable.get("data_type"):
        readable["data_type"] = "asset"
    for field in ("label", "description", "placeholder"):
        if field in readable:
            readable[field] = text_of(readable[field])
    options = readable.get("options")
    if isinstance(options, list):
        readable["options"] = [
            {**option, "label": text_of(option.get("label"))} if isinstance(option, dict) else option
            for option in options
        ]
    return readable


def node_meta(tool: dict[str, Any]) -> dict[str, Any]:
    """一个插件工具的节点元数据,形状与 NODE_TYPES 的条目完全一致。

    插件写了 `node` 就用它的;没写就从 input_schema 生成。两者可以混着来 —— 只想改个标签的
    插件写一行 label 即可,config 仍然自动生成。
    """
    declared = tool.get("node") if isinstance(tool.get("node"), dict) else {}
    config = declared.get("config")
    if isinstance(config, dict) and config:
        config = {str(key): _readable(entry) for key, entry in config.items()}
    else:
        config = _config_from_schema(tool.get("input_schema"))
    outputs = declared.get("outputs")
    if not isinstance(outputs, list) or not outputs:
        # 默认一个口子装整份返回。插件想拆成具名输出就自己声明 outputs。
        outputs = ["output"]
    output_types = declared.get("output_types")
    if not isinstance(output_types, dict):
        output_types = {}
    output_labels = declared.get("output_labels")
    if not isinstance(output_labels, dict):
        output_labels = {}
    #: 在创意画板上跑时,哪几个输出落成新的格子(和 NODE_TYPES 的 board_outputs 同一个意思,缺省全部)。
    board_outputs = declared.get("board_outputs")
    board_outputs = [str(name) for name in board_outputs if str(name) in outputs] if isinstance(board_outputs, list) else []
    #: 画板「添加」菜单里归哪一组、给创作者看的一句说明(和 NODE_TYPES 的同名声明一个意思;不写就由
    #: boards.transforms 按字段和输出推、取说明的第一句)。
    board_group = str(declared.get("board_group") or "")
    board_description = text_of(declared.get("board_description") or "")
    # **给人看的字段一律走 text_of。** 清单里它们可以是 `{"zh": …, "en": …}`,裸 str() 会把
    # 那个字典按 Python 的样子印出来 —— 界面上就是一行 `{'zh': '从百度网盘导入', …}`。
    # 工具的 label/description 在上游已经解过了,而 `node` 这一块是原样透传的,所以解在这里。
    label = text_of(declared.get("label") or tool.get("label") or tool.get("name") or "")
    description = text_of(declared.get("description") or tool.get("description") or "")
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
                "options_from": "plugin_instances",
                # 只接了一个实例时留空即可 —— 正是「留空也能跑」,不该占第一屏。
                "advanced": True,
            },
            **config,
        },
        "outputs": [str(name) for name in outputs],
        "output_types": {str(name): str(data_type) for name, data_type in output_types.items()},
        # 插件可以给专业术语一个更好的名字;未声明的由共用词典/可读降级兜底。
        "output_labels": {str(name): text_of(label) for name, label in output_labels.items()},
        **({"board_outputs": board_outputs} if board_outputs else {}),
        **({"board_group": board_group} if board_group else {}),
        **({"board_description": board_description} if board_description else {}),
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


def instances_for_node(db: Session, node_type: str, user_id: str | None) -> list[dict[str, str]]:
    """这个节点类型可以用哪些实例 —— **这个人自己接的**那些。

    `user_id` 和 `exposed` 一样是必填位置参数,不给默认值:此前默认 None(= 不按人过滤),
    工作流执行器调它时就没传,于是我的流程会自动落到别人接的那条连接上,拿着他的第三方
    密钥跑、记在他的额度上。给个默认值就等于让漏传的地方静默通过。
    """
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


def resolve_instance(db: Session, package_id: str, tool_name: str, chosen: str, actor: str | None) -> str:
    """跑这个工具用哪个连接:选了就用选的;没选而只有一个可用连接时自动用它。

    自动选是有理由的:绝大多数包只会被接一次,逼用户在下拉里点一下那唯一的一项是纯仪式。
    但有多个时**不猜** —— 从 B 站取和从抖音取是两件事,替用户选错比报错更糟。

    候选只有**执行者**(`actor`)自己接的连接:接入归人,别人那条带着别人的密钥和额度。
    选的那条不是他的,就当它不可用 —— 共享的工作流、共享的画板上存着别人选的连接 id,
    照着跑就是拿别人的密钥花别人的额度。工作流节点和画板上的工具走的都是这一条。
    """
    available = instances_for_node(db, node_type_id(package_id, tool_name), actor)
    if chosen:
        if any(item["id"] == chosen for item in available):
            return chosen
        raise PluginDomainError("pluginErr_instanceGone", package=package_id)
    if len(available) == 1:
        return available[0]["id"]
    if not available:
        raise PluginDomainError("pluginErr_noInstance", package=package_id)
    names = [item["name"] for item in available]
    raise PluginDomainError("pluginErr_manyInstances", package=package_id, names=names)


__all__ = [
    "PLUGIN_NODE_CATEGORY",
    "PLUGIN_NODE_PREFIX",
    "node_meta",
    "node_type_id",
    "parse_node_type",
    "plugin_node_types",
    "resolve_instance",
]
