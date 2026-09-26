"""画板上只放**内容变换**(ADR 0021 修订)。

画板和工作流的核心目的不同:工作流是「做一次,跑无数次」—— 步骤、控制流、参数、定时、版本,流程本身
就是产品;画板是「想法摊开,边看边做」—— 素材、便签、生成摆在一起比、挑、改,内容才是主角。画板上的
一个工具回答的是「手里这东西接下来变成什么」(视频转 GIF、转写、翻译、分离人声、降噪、渲 3D 参考、
跑一张出图的 ComfyUI 工作流),不是「然后做哪一步」「把这个值搬到那儿」。

所以一个节点(内置的,或插件工具)要上画板,得是一个内容变换。**规矩从注册表里读,不另列清单**:

1. **不是流程或数据搬运。** 节点的分组不在 `workflows.WIRING_CATEGORIES` 里(流程控制、数据处理、
   知识库)。按分组判,因为光看输出类型分不开 —— 文本模板、字符串处理的输出也是文字。
2. **交出画板摆得下的内容。** 落板的输出里(`board_outputs`,缺省全部)至少有一个是素材
   (`output_data_type == "asset"`:图片 / 视频 / 音频 / 别的文件),或者是**点了名落板**的文字
   (`board_outputs` 里写着、类型是 text)。只有类型没有点名的文字不算:节点交出的文字多半是给
   下游用的摘要、状态、清单(「列出工作流」的 summary、「服务器状态」的一行),一段转写和一行状态
   光看类型分不开,得节点自己说「这段是我的成品」。没声明类型的输出(`any`)也不算 —— 它可能是
   任何东西。
3. **吃画板上的内容,或者凭空产出素材。** 至少有一个字段能接上游的格子(`tools.binding_sink`:
   素材、文字、3D 场景),或者它交出的是素材(文生图、按参数出一段讲解视频、从对象存储取回一个文件)。
   不吃内容、只交出文字的是报告(状态、设置环境的结果),不是创作材料。
4. **必填的字段创作者填得了。** 画板上的表单只摆创作者看得懂的参数(模型、比例、风格、时长、语言
   这一类);映射、原始 JSON、代码、子图这些只有搭流程的人看得懂的字段(`wiring_field`)在画板上
   不出现。一个工具**必填**这种字段的话,它在画板上填不完,不上画板。

同一条规矩管内置节点和插件工具:内置节点还要先在 `NODE_TYPES` 上声明 `surfaces: ["board"]`
(和画板内置的写字 / 生成 / 念重复的、副作用大的,不声明),声明了过不了规矩的由棘轮当场报出来;
插件工具不用声明,按它清单里 `node` 块声明的输出判。插件工具能不能上画板随它接的连接、清单
(ComfyUI 每张工作流一个工具)变,所以规矩在每次取注册表时现算(producers._node_producers),
不缓存;存在画布上、此刻不再合格的工具格,跑的时候说清楚为什么(producers.get_producer)。

画板**怎么摆**一个变换也从这里出:归「添加」菜单的哪一组(`board_group`,按吃什么内容分)、
一句给创作者看的说明(`board_description`)、表单里哪些字段露出来(`board_config_view`)。
"""

from __future__ import annotations

import re
from typing import Any

from app.core.i18n import t
from app.domain.boards.tools import binding_sink

#: 画板「添加」菜单里工具的分组,按**它吃的是什么内容**分,顺序就是菜单里的顺序。
#: `new` 是不吃画板内容、凭空产出素材的(文生图、讲解视频、取回文件);`asset` 是吃素材却没说
#: 哪一种的。标签是 i18n key `boardToolGroup_<组>`。
BOARD_GROUPS: tuple[str, ...] = ("new", "image", "video", "audio", "text", "scene", "asset")

#: 只有搭流程的人看得懂的字段类型:键值映射 / 原始 JSON(object)、代码、子图。
_WIRING_FIELD_TYPES = frozenset({"object", "code", "graph"})


def wiring_field(key: str, spec: Any) -> bool:
    """这个字段是不是工程概念(映射、原始 JSON、代码、子图、声明成 JSON 的模板)—— 画板上不摆。"""
    from app.domain.workflows import config_data_type

    if not isinstance(spec, dict):
        return True
    if spec.get("type") in _WIRING_FIELD_TYPES:
        return True
    return config_data_type(key, spec) == "json"


def _landing(meta: dict[str, Any]) -> list[str]:
    """落板的输出:`board_outputs` 点名的那几个,缺省全部(和 tools.board_outputs 同一条)。"""
    declared = [str(name) for name in meta.get("outputs") or ["output"]]
    return [name for name in (meta.get("board_outputs") or declared) if name in declared]


def content_outputs(meta: dict[str, Any]) -> list[str]:
    """落板的输出里算得上**内容**的那几个:素材,或点了名落板的文字。"""
    from app.domain.workflows import output_data_type

    named = {str(name) for name in meta.get("board_outputs") or ()}
    out = []
    for name in _landing(meta):
        data_type = output_data_type(name, meta)
        if data_type == "asset" or (data_type == "text" and name in named):
            out.append(name)
    return out


def _makes_media(meta: dict[str, Any]) -> bool:
    from app.domain.workflows import output_data_type

    return any(output_data_type(name, meta) == "asset" for name in content_outputs(meta))


def _sinks(meta: dict[str, Any]) -> dict[str, str]:
    """画板上露出来的字段里,能接上游内容的那几个 → 接的是什么(asset / scene / text)。"""
    return {
        key: sink
        for key, spec in (meta.get("config") or {}).items()
        if not wiring_field(key, spec) and (sink := binding_sink(key, spec))
    }


def content_transform_gap(meta: dict[str, Any]) -> str | None:
    """这个节点**差在哪儿**不是一个内容变换;是的话回 None。

    回的是原因的名字(给棘轮和测试说清楚为什么):
    `wiring`(流程 / 数据 / 知识库分组)、`needs_wiring`(必填一个只有搭流程的人看得懂的字段)、
    `no_content_output`(不交出素材,也没点名落板的文字)、`no_content_input`(不吃画板上的内容,
    又只交出文字)。
    """
    from app.domain.workflows import WIRING_CATEGORIES

    if meta.get("category") in WIRING_CATEGORIES:
        return "wiring"
    specs = meta.get("config") or {}
    if any(isinstance(spec, dict) and spec.get("required") and wiring_field(key, spec) for key, spec in specs.items()):
        return "needs_wiring"
    if not content_outputs(meta):
        return "no_content_output"
    if not _makes_media(meta) and not _sinks(meta):
        return "no_content_input"
    return None


def is_content_transform(meta: dict[str, Any]) -> bool:
    return content_transform_gap(meta) is None


def board_group(meta: dict[str, Any]) -> str:
    """它在「添加」菜单里归哪一组。声明了(`board_group`)就用声明的;没声明按它吃的内容推:

    接 3D 场景的归 3D;接素材的归那种素材(字段声明了 `media`,几个素材字段说的是同一种),
    说不清是哪种归「素材」;不吃素材、交出素材的(提示词出图)归「产出新素材」;剩下的吃文字吐文字。
    """
    declared = meta.get("board_group")
    if declared in BOARD_GROUPS:
        return str(declared)
    sinks = _sinks(meta)
    if "scene" in sinks.values():
        return "scene"
    specs = meta.get("config") or {}
    media = {str(specs[key].get("media") or "") for key, sink in sinks.items() if sink == "asset"}
    if media:
        only = next(iter(media)) if len(media) == 1 else ""
        return only if only in ("image", "video", "audio") else "asset"
    return "new" if _makes_media(meta) else "text"


_SENTENCE_END = re.compile(r"(?<=[。!?!?])|(?<=\.)\s")


def board_description(meta: dict[str, Any], locale: str) -> str:
    """给创作者看的一句说明。声明了 `board_description` 就用它;没有就取节点说明的第一句。

    工作流的节点说明是写给搭流程的人的:出口叫什么、`{{上游.输出}}` 怎么引用。第一句里就带着
    这种写法的,宁可不写 —— 菜单上还有名字。
    """
    declared = str(meta.get("board_description") or "").strip()
    if declared:
        return t(declared, locale)
    described = t(str(meta.get("description") or ""), locale).strip()
    first = _SENTENCE_END.split(described, maxsplit=1)[0].strip() if described else ""
    return "" if "{{" in first else first


def board_config_view(config: dict[str, Any]) -> dict[str, Any]:
    """画板表单上露出来的字段(一份已经按语言翻好的节点字段声明 → 画板那一份)。

    · 映射、原始 JSON、代码、子图(wiring_field)不出现;
    · 模板字段在画板上就是一段字(`type: "text"`):画板上没有「上游的输出」可引用,上游是连进来的
      格子(`board_sources`),`{{…}}` 这种写法不该出现在创作者面前;
    · 说明里教 `{{…}}` 写法的那一句(写给工作流的)不带过来。
    """
    view: dict[str, Any] = {}
    for key, spec in config.items():
        if wiring_field(key, spec):
            continue
        field = dict(spec)
        if field.get("type") == "template":
            field["type"] = "text"
        if "{{" in str(field.get("description") or ""):
            field.pop("description", None)
        view[key] = field
    return view


__all__ = [
    "BOARD_GROUPS",
    "board_config_view",
    "board_description",
    "board_group",
    "content_outputs",
    "content_transform_gap",
    "is_content_transform",
    "wiring_field",
]
