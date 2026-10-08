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

import logging
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.i18n import is_message_key, tr
from app.domain.media_kinds import MEDIA_KINDS
from app.domain.plugins.errors import PluginDomainError
from app.domain.plugins.inputs import ASSET_FORMAT, EXTERNAL_ID_FORMAT, schema_type
from app.domain.plugins.manifest import TOOLS, text_of, tool_label

logger = logging.getLogger(__name__)

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
    #: 数组给「一串」编辑器(一行一项),不是「名字 → 值」的映射:此前映到 object,存下去的是 `{"a": …}`,
    #: 交给插件的就不是数组。素材数组另有 asset_list(见 _config_from_schema)。
    "array": "list",
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


def _media(declared: Any) -> str | list[str] | None:
    """`x-media` → 节点声明的 `media`,和内置节点同一个写法:一种是字符串,几种是列表;认不出的丢掉。"""
    from app.domain.media_kinds import declared_media

    kinds = declared_media(declared)
    if not kinds:
        return None
    return kinds[0] if len(kinds) == 1 else list(kinds)


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
        # 联合类型(["string","null"])取第一个非 null 的分支 —— 表单只能长一个样子(和运行时同一条 schema_type)。
        raw_type = schema_type(spec)
        entry: dict[str, Any] = {"type": _SCHEMA_TYPES.get(str(raw_type), "template")}
        if key in required:
            entry["required"] = True
        # 界面上叫什么:JSON Schema 的 `title`(可以按语言分)。不写就由节点目录按键名给一个可读名。
        if spec.get("title"):
            entry["label"] = text_of(spec["title"])
        # 插件用 `format: asset` 声明「这是一份素材」(运行时据此换成本地路径,见 inputs)。
        # 类型跟着声明走,不靠字段名碰运气:字段不叫 asset_id 时,命名约定认不出它,
        # 工作流里就拿不到素材选择器。`x-media` 说是哪几种素材(`"image"`,或 `["audio", "video"]`),
        # 选择器只列那几种,画板上也只有那几种格子接得上(workflows.config_media)。
        items = spec.get("items") if isinstance(spec.get("items"), dict) else {}
        if spec.get("format") == ASSET_FORMAT:
            entry["data_type"] = "asset"
        elif raw_type == "array" and items.get("format") == ASSET_FORMAT:
            # 一串素材:给能挑好几份的选择器,不是一个让人手写 `["…"]` 的 JSON 框
            entry = {**entry, "type": "asset_list", "data_type": "asset"}
            items_media = _media(items.get("x-media"))
            if items_media:
                entry["media"] = items_media
        elif raw_type == "array" and schema_type(items) in ("object", "array"):
            # 每一项是一块结构(标题 + 正文、一组参数):拍成一行一个值是错的。每一项声明了有哪几格的,
            # 一项一张卡、按那几格填(_structure_fields);说不出有哪几格的,才退回写数组的 JSON 框。
            fields = _structure_fields(items, depth=1)
            entry.update({"editor": "items", "fields": fields} if fields else {"editor": "json"})
        elif spec.get("format") == EXTERNAL_ID_FORMAT:
            # 另一个系统里的编号(任务号、fs_id、对象路径):工作流里照样能接上游、能手填,画板据此认出
            # 「按编号去外面取东西」的工具(workflows.EXTERNAL_ID、boards.transforms)。
            entry["data_type"] = EXTERNAL_ID_FORMAT  # format 名就是 data_type 名,和 asset 一样
        media = _media(spec.get("x-media"))
        if media:
            entry["media"] = media
        if spec.get("description"):
            entry["description"] = text_of(spec["description"])
        enum = spec.get("enum")
        if isinstance(enum, list) and enum:
            entry["options"] = [str(value) for value in enum]
        elif entry["type"] == "list" and isinstance(items.get("enum"), list) and items["enum"]:
            # 一串、每一项只能是这几个值之一:表单给多选(挑出来的一排),不是让人一行一行手写还写错
            entry["options"] = [str(value) for value in items["enum"]]
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
        if entry["type"] in ("list", "asset_list"):
            entry.update(_item_bounds(spec))
        # 「留空也能跑的专业旋钮」收进高级区,和内置节点同一套语义(NODE_TYPES 的 advanced)。
        # JSON Schema 没有这个概念,所以认 `x-advanced` 这个扩展键;直接写 `advanced` 也认 ——
        # 插件作者八成会先试后者,为一个拼写把人挡在门外不值得。
        if spec.get("x-advanced") is True or spec.get("advanced") is True:
            entry["advanced"] = True
        config[key] = entry
    return config


def _item_bounds(spec: dict[str, Any]) -> dict[str, int]:
    """数组的 `minItems` / `maxItems` → 表单上的 `min_items` / `max_items`:删到下限就不让删,加到上限就不再给「加一项」。"""
    bounds: dict[str, int] = {}
    for source, target in (("minItems", "min_items"), ("maxItems", "max_items")):
        value = spec.get(source)
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
            bounds[target] = value
    return bounds


#: 结构化编辑器往里展开几层。讲解步骤(第 1 层)里的函数图(第 2 层)还摊成几格;再往里就是一块自由结构,
#: 给一个 JSON 小框 —— 卡片套卡片套卡片,侧栏那点宽度里已经读不出谁是谁的哪一格了。
_STRUCTURE_DEPTH = 2


def _structure_fields(schema: dict[str, Any], *, depth: int) -> dict[str, dict[str, Any]]:
    """一块结构(数组里的一项、一个对象)有哪几格,每一格怎么填。说不出有哪几格的(没写 `properties`)回空。

    和顶层字段同一套读法(title / description 按语言、enum 给下拉、`x-multiline` 给多行),但词汇更小:
    这些格子不接上游、不进高级区,值存的是文字 —— 按声明转回数、布尔的是运行时那一处(inputs.coerce)。
    """
    properties = schema.get("properties")
    if not isinstance(properties, dict) or not properties:
        return {}
    required = {key for key in (schema.get("required") or []) if isinstance(key, str)}
    return {
        str(key): _structure_field(spec if isinstance(spec, dict) else {}, required=key in required, depth=depth)
        for key, spec in properties.items()
    }


def _structure_field(spec: dict[str, Any], *, required: bool, depth: int) -> dict[str, Any]:
    """结构里的一格 → 表单声明。`type`:text / number / boolean / list / object;一串结构、一个对象再往里说不清
    (没写 properties,或已经到了 _STRUCTURE_DEPTH)的,和顶层同一个写法:`editor: "json"`。"""
    kind = schema_type(spec)
    items = spec.get("items") if isinstance(spec.get("items"), dict) else {}
    entry: dict[str, Any]
    if kind in ("integer", "number"):
        entry = {"type": "number"}
    elif kind == "boolean":
        entry = {"type": "boolean", "options": ["true", "false"]}
    elif kind == "array" and schema_type(items) not in ("object", "array"):
        entry = {"type": "list", **_item_bounds(spec)}
        if isinstance(items.get("enum"), list) and items["enum"]:
            entry["options"] = [str(value) for value in items["enum"]]
    elif kind == "array":
        fields = _structure_fields(items, depth=depth + 1) if depth < _STRUCTURE_DEPTH else {}
        entry = {"type": "list", "editor": "items", "fields": fields} if fields else {"type": "list", "editor": "json"}
        entry.update(_item_bounds(spec))
    elif kind == "object":
        fields = _structure_fields(spec, depth=depth + 1) if depth < _STRUCTURE_DEPTH else {}
        entry = {"type": "object", "editor": "fields", "fields": fields} if fields else {"type": "object", "editor": "json"}
    else:
        entry = {"type": "text"}
        if spec.get("x-multiline") is True:
            entry["multiline"] = True
    if entry["type"] in ("text", "number") and isinstance(spec.get("enum"), list) and spec["enum"]:
        entry["options"] = [str(value) for value in spec["enum"]]
    if required:
        entry["required"] = True
    if spec.get("title"):
        entry["label"] = text_of(spec["title"])
    if spec.get("description"):
        entry["description"] = text_of(spec["description"])
    default = spec.get("default")
    if isinstance(default, bool):
        entry["default"] = "true" if default else "false"
    elif isinstance(default, (str, int, float)) and str(default) != "":
        entry["default"] = str(default)
    return entry


def _readable(entry: Any, from_schema: dict[str, Any] | None) -> dict[str, Any]:
    """插件自己声明的一条 config,把其中给人看的字段本地化,并**按 input_schema 对齐**「它装的是什么」。其余原样透传。

    是不是素材、是不是一串,**只听 input_schema**(`from_schema` 是同一格从 schema 生成的那条):运行时把素材 id
    换成本地路径(inputs.asset_fields / materialize)、把表单里的文字转回数组(inputs.coerce)看的都是 schema。
    此前 node.config 自己说了算 —— 它写了 `format: asset` 而 schema 没写,表单给素材选择器、运行时却把素材 id
    原样交给插件;反过来 schema 是素材而 node.config 没写,运行时换路径、表单却只给一个文本框。
    """
    if not isinstance(entry, dict):
        return {}
    readable = {key: value for key, value in entry.items() if not (key == "format" and value == ASSET_FORMAT)}
    if readable.get("data_type") == "asset":
        readable.pop("data_type")
    if from_schema is not None:
        if from_schema.get("data_type") == "asset":
            readable["data_type"] = "asset"
            if from_schema.get("media") and not readable.get("media"):
                readable["media"] = from_schema["media"]
        if from_schema.get("type") in ("asset_list", "list"):
            readable["type"] = from_schema["type"]
            # 每一项长什么样(有哪几格、几项起几项止)也只有 schema 说得准:运行时按它转值
            for key in ("editor", "fields", "min_items", "max_items"):
                if key in from_schema:
                    readable[key] = from_schema[key]
    if readable.get("type") in ("asset_list", "list") and (from_schema or {}).get("type") not in ("asset_list", "list"):
        # node.config 自己说「一串」而 schema 不是数组:运行时不会把它转成数组(inputs.coerce 只听 schema),
        # 表单却存下一个列表交给插件。降回 schema 那一格的样子(schema 里没有这一格就是一段文字)。
        readable["type"] = (from_schema or {}).get("type") or "template"
        for key in ("editor", "fields", "min_items", "max_items"):
            readable.pop(key, None)
    if readable.get("format") == EXTERNAL_ID_FORMAT and not readable.get("data_type"):
        readable["data_type"] = EXTERNAL_ID_FORMAT
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


def declared_outputs(tool: dict[str, Any]) -> list[str]:
    """这个工具作为节点有哪些输出口:`node.outputs` 声明了就是它们;没声明是一个装整份返回的 `output`。

    节点元数据、执行器按口取值、改写被取代的工具时核对下游引用(workflows.plugin_references)读的都是这一条。
    """
    declared = tool.get("node") if isinstance(tool.get("node"), dict) else {}
    outputs = declared.get("outputs")
    return [str(name) for name in outputs] if isinstance(outputs, list) and outputs else ["output"]


def node_meta(tool: dict[str, Any]) -> dict[str, Any]:
    """一个插件工具的节点元数据,形状与 NODE_TYPES 的条目完全一致。

    插件写了 `node` 就用它的;没写就从 input_schema 生成。两者可以混着来 —— 只想改个标签的
    插件写一行 label 即可,config 仍然自动生成。
    """
    declared = tool.get("node") if isinstance(tool.get("node"), dict) else {}
    config = declared.get("config")
    from_schema = _config_from_schema(tool.get("input_schema"))
    if isinstance(config, dict) and config:
        config = {str(key): _readable(entry, from_schema.get(str(key))) for key, entry in config.items()}
    else:
        config = from_schema
    #: 字段装的是什么只听 schema 的 format(素材 / 外部编号)。内置节点那套按名字推(`asset_id` → 素材,
    #: workflows.config_data_type)是写给内置节点作者的约定;插件的 `asset_id` 可能是另一个系统里的编号 ——
    #: 按名字推成素材,表单给素材选择器、画板接媒体格,运行时却不换路径(inputs.asset_fields 只听 format)。
    #: 没说的显式写成 any,名字推断就不再起作用。
    config = {key: {**entry, "data_type": entry.get("data_type") or "any"} for key, entry in config.items()}
    from app.domain.plugins.tools import COLLECTED_AS

    outputs = declared_outputs(tool)
    output_types = declared.get("output_types")
    output_types = dict(output_types) if isinstance(output_types, dict) else {}
    #: 输出口叫 `artifact` / `artifacts` 的就是插件交出的文件(收产出时换成了素材 id,见 tools.COLLECTED_AS):
    #: 没声明类型时它们是素材 —— 否则按 any 处理,画板把一串素材 id 落成写着 id 的便签,工作流连线也认不出它是素材。
    for name in outputs:
        if name in COLLECTED_AS and name not in output_types:
            output_types[name] = "asset"
    output_labels = declared.get("output_labels")
    if not isinstance(output_labels, dict):
        output_labels = {}
    #: 在创意画板上跑时,哪几个输出落成新的格子(和 NODE_TYPES 的 board_outputs 同一个意思,缺省全部)。
    board_outputs = declared.get("board_outputs")
    board_outputs = [str(name) for name in board_outputs if str(name) in outputs] if isinstance(board_outputs, list) else []
    #: 素材输出是哪种素材(`{输出名: image | video | audio}`):画板上生成器据此挂在那种素材的空格子上
    #: (boards.transforms.output_kinds)。认不出的项丢掉。
    output_media = declared.get("output_media")
    output_media = (
        {str(name): kind for name, kind in output_media.items() if str(name) in outputs and kind in MEDIA_KINDS}
        if isinstance(output_media, dict) else {}
    )
    #: 只给工作流连线用的输出(id、个数、摘要、任务号):画板上**从不**落成格子(见 boards.tools.landing_outputs)。
    wiring_outputs = declared.get("wiring_outputs")
    wiring_outputs = [str(name) for name in wiring_outputs if str(name) in outputs] if isinstance(wiring_outputs, list) else []
    #: 这个工具和一个生成模型是同一件事(运行时报出的工具才有,见 plugins.tools.all_tools)。
    mirrors = tool.get("mirrors") if isinstance(tool.get("mirrors"), dict) else None
    #: 画板「添加」菜单里归哪一组、给创作者看的一句说明(和 NODE_TYPES 的同名声明一个意思;不写就由
    #: boards.transforms 按字段和输出推、取说明的第一句)。
    board_group = str(declared.get("board_group") or "")
    board_description = text_of(declared.get("board_description") or "")
    # **给人看的字段一律走 text_of。** 清单里它们可以是 `{"zh": …, "en": …}`,裸 str() 会把
    # 那个字典按 Python 的样子印出来 —— 界面上就是一行 `{'zh': '从百度网盘导入', …}`。
    # 工具的 label/description 在上游已经解过了,而 `node` 这一块是原样透传的,所以解在这里。
    #: 名字只有一条解析(manifest.tool_label):清单的名字 → node 块的名字 → 调用名。从不拿说明顶替。
    label = tool_label(tool)
    description = text_of(declared.get("description") or tool.get("description") or "")
    if mirrors is not None and description:
        #: 节点面板上说一声:只要那一种成片的话,「AI 生成素材」节点选这个模型是同一件事(还有回执、用量、
        #: 6 小时)。按声明的种类挑一句,不认识的种类不说。
        hint = f"pluginNode_mirroredByGeneration_{mirrors.get('kind')}"
        if is_message_key(hint):
            description = f"{description}\n{tr(hint)}"
    return {
        "label": label,
        # 面板上每行都有一句说明;插件没写就退到"来自哪个插件",总比空着强。
        "description": description or f"来自插件「{tool.get('package_name', '')}」的工具。",
        "category": PLUGIN_NODE_CATEGORY,
        # 「用哪个连接」是节点的一个普通配置项,和别的字段走同一套表单与校验。
        "config": {
            "instance_id": {
                "type": "string",
                "description": "用哪个连接(同一个插件可以接多个)",
                "options_from": "plugin_instances",
                # 只接了一个实例时留空即可 —— 正是「留空也能跑」,不该占第一屏。
                "advanced": True,
                # 留空时用的就是那唯一的一条(resolve_instance),表单把它显示成当前值。
                "sole_option_default": True,
            },
            **config,
        },
        "outputs": [str(name) for name in outputs],
        "output_types": {str(name): str(data_type) for name, data_type in output_types.items()},
        # 插件可以给专业术语一个更好的名字;未声明的由共用词典/可读降级兜底。
        "output_labels": {str(name): text_of(label) for name, label in output_labels.items()},
        **({"board_outputs": board_outputs} if board_outputs else {}),
        **({"wiring_outputs": wiring_outputs} if wiring_outputs else {}),
        **({"output_media": output_media} if output_media else {}),
        **({"mirrors": mirrors} if mirrors is not None else {}),
        **({"board_group": board_group} if board_group else {}),
        **({"board_description": board_description} if board_description else {}),
        # 前端据此在节点上标出处;也让"缺插件"的报错说得出是谁。是**插件**的名字,不是连接名:
        # 节点按包聚合,连接名(「阿里云 OSS · 某个桶」)只是碰巧排在第一的那条连接。
        "plugin_name": tool.get("package_name", ""),
        "tool_name": tool.get("name", ""),
        # 哪样东西的哪个入口(ADR 0045,ComfyUI 一张工作流的完整工作流和表单):添加节点、画布上的节点据此写第二行「来自 X」
        **({"group": tool["group"]} if tool.get("group") else {}),
    }


def plugin_node_types(db: Session, user_id: str | None = None) -> dict[str, dict[str, Any]]:
    """当前可用的插件节点类型。可用实例(启用 + 配置齐 + 凭据齐 + 已授权)暴露的工具才在列。

    **这份注册表是动态的**,这正是它不能并进 NODE_TYPES 的原因:NODE_TYPES 是这份代码的
    常量(有测试钉着它和执行器一一对应),而装了什么插件是用户机器上的事实。

    **节点类型按包聚合,不按实例**:同一个包的两个实例(B站 / 抖音)提供的是同一批节点,
    选哪个实例是节点 config 里的一个字段。工作流会被导出到别的机器,而实例是本机事实 ——
    绑包的话,导出的图在别人机器上缺的是"连接"(可以现场建);绑实例的话缺的是"节点类型",
    图直接打不开。几条连接报的同一个节点入参不一样时怎么合,见 _across_connections。
    """
    from app.domain.plugins.tools import exposed

    reported: dict[str, list[dict[str, Any]]] = {}
    for tool in exposed(db, user_id):
        reported.setdefault(node_type_id(tool["package_id"], tool["name"]), []).append(tool)
    return {key: _across_connections(tools) for key, tools in reported.items()}


def _across_connections(tools: list[dict[str, Any]]) -> dict[str, Any]:
    """同一个节点类型在几条连接上各报了一份 —— 运行时报的工具名可能撞上:ComfyUI 的工具名取自工作流的图 id,同一个文件
    拷到两台 ComfyUI 上、各自改过,入参就不一样。此前只留第一条连接的那份:绑在第二条上的节点,表单里是第一条的那几格
    (填了插件丢掉、不生效),它自己多出来的那几格填不了。

    现在表单取各条连接的入参的**并集**;只有部分连接上有的那几格,标上 `active_when: {instance_id: [这几条连接]}` ——
    节点选了那几条之一才出现、才参与校验(和别的条件字段同一条规矩,前后端都认,见 workflows.field_activation)。
    同名的一格在几条连接上声明得不一样(选项、默认值)时,照第一条的。名字、说明、输出也照第一条的。
    """
    meta = node_meta(tools[0])
    if len(tools) == 1:
        return meta
    configs = [(str(tool.get("instance_id") or ""), node_meta(tool)["config"]) for tool in tools]
    config = dict(meta["config"])
    for _, own in configs[1:]:
        for name, spec in own.items():
            config.setdefault(name, spec)
    for name, spec in list(config.items()):
        having = [instance for instance, own in configs if name in own]
        if name != "instance_id" and len(having) < len(configs):
            conditions = spec.get("active_when") if isinstance(spec.get("active_when"), dict) else {}
            config[name] = {**spec, "active_when": {**conditions, "instance_id": having}}
    return {**meta, "config": config}


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


@dataclass(frozen=True)
class Unusable:
    """一个插件节点为什么用不了(`error`,给人看的那句),和修法是不是到某个连接自己的库里升级(`upgrade_in`:那个连接的 id;
    不是就空串 —— ComfyUI 上那张工作流的表单还是上一版格式,工作流库里「查看并升级」,ADR 0045 修订之二)。"""

    error: PluginDomainError
    upgrade_in: str = ""


def why_unusable(db: Session, node_type: str, user_id: str | None) -> PluginDomainError | None:
    """这个插件节点**这个人**为什么用不了;用得了回 None(详见 unusable)。"""
    found = unusable(db, node_type, user_id)
    return found.error if found is not None else None


def unusable(db: Session, node_type: str, user_id: str | None) -> Unusable | None:
    """这个插件节点**这个人**为什么用不了;用得了回 None。

    `exposed` 把用不了的连接、没勾选的工具一律滤掉,于是此前所有情况只剩一句「没有可用的连接」(还报的是
    包 id):插件被删了、连接停用了、凭据过期了、工具没勾选、插件升级后这个工具没了 —— 该去的地方各不相同。
    这里按真实原因说:插件不在 → 没装;没有他的连接 → 去接一个;有连接 → 逐条说每个连接卡在哪。连接好好的、清单上就是
    没有它:运行时才知道工具的插件(ComfyUI 每张工作流一个)问插件为什么(`op: explain`,见 _explained)—— 表单是旧格式要升级、
    表单删了、工作流改名挪走了,各说各的;问不到才说「插件更新后去掉了它」。
    """
    from app.db.models import PluginInstance, PluginPackage
    from app.domain.plugins import instances as inst
    from app.domain.plugins.manifest import manifest_of
    from app.domain.plugins.tools import all_tools

    parsed = parse_node_type(node_type)
    if parsed is None:
        return None
    package_id, tool_name = parsed
    package = db.get(PluginPackage, package_id)
    if package is None:
        return Unusable(PluginDomainError("pluginErr_nodePluginMissing", plugin=package_id))
    try:
        plugin = manifest_of(package).name or package_id
    except ValueError:  # 清单坏了(ManifestError):照包 id 说
        plugin = package_id
    stmt = select(PluginInstance).where(PluginInstance.package_id == package_id)
    if user_id is not None:
        stmt = stmt.where(PluginInstance.owner_user_id == user_id)
    connections = list(db.scalars(stmt))
    if not connections:
        return Unusable(PluginDomainError("pluginErr_nodeNoConnection", plugin=plugin))
    tool_shown = tool_name
    upgrade_in = ""
    details: list[str] = []
    for instance in connections:
        # 先认出工具叫什么,再看连接卡在哪:被挡的连接缓存着的清单里也有它的名字 —— 此前被挡就直接跳过,
        # 报错里露的是调用名(ComfyUI 每张工作流一个的 `wf_<哈希>`),用户认不出是哪个。
        tool = next((one for one in _tools_of(db, instance, all_tools) if one["name"] == tool_name), None)
        if tool is not None:
            tool_shown = tool_label(tool) or tool_name
        blocked = inst.blocked_reason(db, instance)
        if blocked:
            details.append(tr("pluginWhy_connection", name=instance.name, reason=blocked))
            continue
        if tool is None:
            # 清单上没有它:清单上一次没拉下来时说那个原因(服务没开、超时)—— 那时说「插件更新后去掉了它」是错的,
            # 该去的地方是把服务开起来、再刷新一次,不是换一个工具。清单好好的,问插件为什么(见 _explained)。
            failed = _tool_list_failure(instance)
            explained = None if failed else _explained(db, instance, tool_name)
            if failed:
                reason = tr("pluginWhy_toolListFailed", reason=failed)
            elif explained is not None:
                reason = text_of(explained.reason)
                tool_shown = text_of(explained.label) or tool_shown
                upgrade_in = upgrade_in or (instance.id if explained.upgrade else "")
            else:
                reason = tr("pluginWhy_toolGone")
            details.append(tr("pluginWhy_connection", name=instance.name, reason=reason))
            continue
        if tool["internal"]:
            details.append(tr("pluginWhy_connection", name=instance.name, reason=tr("pluginWhy_toolInternal")))
        elif tool_name not in inst.exposed_tools(db, instance.id):
            details.append(tr("pluginWhy_connection", name=instance.name, reason=tr("pluginWhy_toolNotExposed")))
        else:
            return None
    return Unusable(PluginDomainError(
        "pluginErr_nodeUnusable", plugin=plugin, tool=tool_shown, details=tr("punct_listSep").join(details)
    ), upgrade_in)


def _explained(db: Session, instance: Any, tool_name: str) -> Any:
    """问这个连接的插件:清单上为什么没有这个工具(只问运行时才报工具的那种插件,见 dynamic_tools.explain)。不支持这一问、
    这会儿问不到都是 None —— 退回宿主自己能说的那句,不让一句解释拖垮整件事。"""
    from app.domain.plugins import dynamic_tools
    from app.domain.plugins import instances as inst

    try:
        manifest = inst.manifest_for(db, instance)
        if TOOLS not in manifest.provides or manifest.is_mcp:
            return None
        return next((one for one in dynamic_tools.explain(db, instance, [tool_name]) if one.name == tool_name), None)
    except Exception:  # noqa: BLE001 — 解释不出来不是错
        logger.info("插件实例 %s 解释不了工具 %s 为什么不在", getattr(instance, "id", ""), tool_name, exc_info=True)
        return None


def _tools_of(db: Session, instance: Any, all_tools: Any) -> list[dict[str, Any]]:
    """这条连接此刻的工具清单;读不出来(包记录的清单坏了)当它没有。"""
    try:
        return all_tools(db, instance)
    except ValueError:  # PluginDomainError / ManifestError 都是 ValueError
        return []


def _tool_list_failure(instance: Any) -> str:
    """这条连接的工具清单上一次没刷出来的原因(instances.record_tool_list_failure 记的);刷成功过就是空串。
    按读的人的语言说(落库的是文案 key + 参数,和插件页同一个读法)。"""
    from app.core.i18n import get_current_locale, render_message

    status = (instance.capability_status or {}).get(TOOLS) or {}
    key = str(status.get("error_key") or "")
    if key:
        return render_message(key, get_current_locale(), status.get("error_params") or {})
    return str(status.get("error") or "")


def resolve_instance(db: Session, package_id: str, tool_name: str, chosen: str, actor: str | None) -> str:
    """跑这个工具用哪个连接:选了就用选的;没选而只有一个可用连接时自动用它。

    自动选是有理由的:绝大多数包只会被接一次,逼用户在下拉里点一下那唯一的一项是纯仪式。
    但有多个时**不猜** —— 从 B 站取和从抖音取是两件事,替用户选错比报错更糟。

    候选只有**执行者**(`actor`)自己接的连接:接入归人,别人那条带着别人的密钥和额度。
    选的那条不在他能用的连接里时分两种:
    - 是**他自己的**(停用了、凭据过期了):他点名要的就是那一条,替他换成别的就是替他选 —— 报「选的连接不可用」;
    - 是别人的、或者已经删了:那不是他的选择,是共享的工作流 / 画板上存着别人选的连接,或一个不存在的 id ——
      当作没选,按他自己的连接挑(只有一条就用它),别人的连接一句不提。
    此前工作流节点在后一种情况也报「选的连接已不可用」,而开跑前的检查只看节点类型,于是放行之后跑到这一步才失败;
    画板上的工具一直是「当作没选」。现在工作流节点、画板上的工具和开跑前的检查(check_plugin_node_instance)
    走的都是这一条。
    """
    node_type = node_type_id(package_id, tool_name)
    available = instances_for_node(db, node_type, actor)
    if chosen:
        if any(item["id"] == chosen for item in available):
            return chosen
        if available and _owned_by(db, chosen, actor):
            raise PluginDomainError("pluginErr_instanceGone", package=_plugin_name(db, package_id))
    if len(available) == 1:
        return available[0]["id"]
    if not available:
        raise why_unusable(db, node_type, actor) or PluginDomainError(
            "pluginErr_noInstance", package=_plugin_name(db, package_id)
        )
    names = [item["name"] for item in available]
    raise PluginDomainError("pluginErr_manyInstances", package=_plugin_name(db, package_id), names=names)


def _owned_by(db: Session, instance_id: str, actor: str | None) -> bool:
    """这条连接还在、而且是 `actor` 自己接的(没有执行者 = 不按人分,和 instances_for_node 一样)。"""
    from app.db.models import PluginInstance

    instance = db.get(PluginInstance, instance_id)
    return instance is not None and (actor is None or instance.owner_user_id == actor)


def check_plugin_node_instance(db: Session, node: dict[str, Any], actor: str | None) -> PluginDomainError | None:
    """开跑前问一遍:这个插件节点轮到它时,`actor` 落得到一条连接吗?落得到回 None,落不到回那句报错。

    和执行时是**同一条**规矩(resolve_instance):有几条可挑、选的那条是不是他的,判法一字不差 —— 否则开跑前
    放行的,跑到这一步照样失败(前面的节点钱已经花了)。连接选的是一段引用(`{{…}}`)时值要到运行时才知道,不判。
    不是插件节点回 None。
    """
    parsed = parse_node_type(str(node.get("type") or ""))
    if parsed is None:
        return None
    config = node.get("config") if isinstance(node.get("config"), dict) else {}
    chosen = config.get("instance_id")
    if isinstance(chosen, str) and "{{" in chosen:
        return None
    try:
        resolve_instance(db, parsed[0], parsed[1], str(chosen or ""), actor)
    except PluginDomainError as exc:
        return exc
    return None


def _plugin_name(db: Session, package_id: str) -> str:
    """报错里说插件叫什么(清单上的名字,按此刻的语言);包没了或清单坏了就说包 id。"""
    from app.db.models import PluginPackage
    from app.domain.plugins.manifest import manifest_of

    package = db.get(PluginPackage, package_id)
    try:
        return (manifest_of(package).name if package is not None else "") or package_id
    except ValueError:
        return package_id


__all__ = [
    "PLUGIN_NODE_CATEGORY",
    "PLUGIN_NODE_PREFIX",
    "Unusable",
    "check_plugin_node_instance",
    "declared_outputs",
    "node_meta",
    "node_type_id",
    "parse_node_type",
    "plugin_node_types",
    "resolve_instance",
    "unusable",
    "why_unusable",
]
