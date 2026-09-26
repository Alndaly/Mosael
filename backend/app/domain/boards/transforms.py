"""画板上只放**内容变换**(ADR 0021 修订)。

画板和工作流的核心目的不同:工作流是「做一次,跑无数次」—— 步骤、控制流、参数、定时、版本,流程本身
就是产品;画板是「想法摊开,边看边做」—— 素材、便签、生成摆在一起比、挑、改,内容才是主角。画板上的
一个工具回答的是「手里这东西接下来变成什么」(视频转 GIF、转写、翻译、分离人声、降噪、渲 3D 参考、
跑一张出图的 ComfyUI 工作流),不是「然后做哪一步」「把这个值搬到那儿」。

所以一个节点(内置的,或插件工具)要上画板,得是一个内容变换。**规矩从注册表里读,不另列清单**:

1. **不是流程或数据搬运。** 节点的分组不在 `workflows.WIRING_CATEGORIES` 里(流程控制、数据处理、
   知识库)。按分组判,因为光看输出类型分不开 —— 文本模板、字符串处理的输出也是文字。
2. **交出画板摆得下的内容。** 落板的输出里(`tools.landing_outputs`:`board_outputs` 点名的,缺省是全部
   不是只给连线用的 —— `wiring_outputs` 从不落板)至少有一个是素材
   (`output_data_type == "asset"`:图片 / 视频 / 音频 / 别的文件),或者是**点了名落板**的文字
   (`board_outputs` 里写着、类型是 text)。只有类型没有点名的文字不算:节点交出的文字多半是给
   下游用的摘要、状态、清单(「列出工作流」的 summary、「服务器状态」的一行),一段转写和一行状态
   光看类型分不开,得节点自己说「这段是我的成品」。没声明类型的输出(`any`)也不算 —— 它可能是
   任何东西。
3. **吃画板上的内容,或者凭空产出素材。** 至少有一个字段能接上游的格子(`tools.binding_sink`:
   素材、文字、3D 场景),或者它交出的是素材(文生图、按参数出一段讲解视频)。
   不吃内容、只交出文字的是报告(状态、设置环境的结果),不是创作材料。
4. **必填的字段创作者填得了。** 画板上的表单只摆创作者看得懂的参数(模型、比例、风格、时长、语言
   这一类);映射、原始 JSON、代码、子图这些只有搭流程的人看得懂的字段(`wiring_field`)在画板上
   不出现。一个工具**必填**这种字段的话,它在画板上填不完,不上画板。
5. **不按另一个系统里的编号去取东西。** 字段声明了 `external_id`(workflows.EXTERNAL_ID:ComfyUI 的任务号、
   网盘的 fs_id、对象存储的对象路径)的工具,是在**寻址**一个外部系统:必填这种字段的,创作者在画板上填不出来
   (得去别的系统抄一串编号);不吃画板内容、却收这种字段的(哪怕选填),交出的素材是按编号从外面取回来的,
   不是「凭空产出」—— 第 3 条的「凭空产出素材」说的是按参数做出来(提示词出图、按参数出视频)。导入该走
   素材库和拖放;按编号取回是流程里的一步(列清单 → 取回),归工作流和智能体。这种字段也不接上游格子
   (便签上的字不是任务号,tools.binding_sink),画板的表单上不出现。
6. **一个概念一个入口。** 插件报出的工具声明了 `mirrors`(它和某个生成模型是同一件事,ComfyUI 里只有一个
   存下来的图 / 视频 / 音频输出节点的工作流就是 —— 预览节点不算),而点运行的这个人在生成目录里用得上
   那个模型时,画板上只留生成(图片 / 视频 / 音频格选那个模型:结果落在原位、有张数、用量、6 小时),
   不再列出它。工作流里两个都在。
   「用得上」要按人、按连接问,规矩本身不查库:调用方(producers._node_producers)把答案递进来。

同一条规矩管内置节点和插件工具:内置节点还要先在 `NODE_TYPES` 上声明 `surfaces: ["board"]`
(和画板内置的写字 / 生成 / 念重复的、副作用大的,不声明),声明了过不了规矩的由棘轮当场报出来;
插件工具不用声明,按它清单里 `node` 块声明的输出判。插件工具能不能上画板随它接的连接、清单
(ComfyUI 每张工作流一个工具)变,所以规矩在每次取注册表时现算(producers._node_producers),
不缓存;存在画布上、此刻不再合格的能力或生成器,跑的时候说清楚为什么(producers.get_producer)。空格子上
被生成取代的生成器由对账改挂生成(boards.plugin_references)。

画板**怎么摆**一个变换也从这里出:它是哪一格的能力(`board_role` / `board_hosts` / `host_field`,
ADR 0025 修订「能力住在内容格上」)、一句给创作者看的说明(`board_description`)、表单里哪些字段露出来
(`board_config_view`)、按吃什么内容归的组(`board_group`,图标兜底用)。

**画板上没有单独的工具格。** 一个内容变换是**内容格自己的能力**(音频格会转写、分离、降噪,便签会翻译),
或者是**空格子的一种填法**(按参数出图、出片的生成器,和「配音 / 生成」同一个切换):

· `ability` —— 吃画板上的内容:挂在它那个内容字段收得下的几种格子上(`board_hosts`),宿主那一格的内容
  就是那个字段的值(`host_field`:便签给字、文档给钉住那一版的正文、媒体给素材、3D 场景给场景),产出新建在
  宿主右边;
· `slot` —— 不吃画板内容、凭空产出一种素材:挂在那种素材的空格子上(产出种类见 output_kinds),产出填进那一格。

判法只看声明,不为哪个工具写特例:画板上露出来、能接上游的字段里有素材 / 3D 场景字段的,是那几种格子的能力;
只有文字字段、而且只交出文字的(翻译、改写),是便签 / 文档的能力;只有文字字段却交出素材的(提示词出图),
文字是它的参数不是它的原料 —— 和内置的「生成」一样,是空格子的一种填法。
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

from app.core.i18n import t
from app.domain.boards.tools import binding_sink, landing_outputs

#: 变换按**它吃的是什么内容**归的组(界面上能力图标的兜底、智能体读的分类),顺序就是接口里排的顺序。
#: `new` 是不吃画板内容、凭空产出素材的(文生图、讲解视频);`asset` 是吃素材却没说
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


def external_id_field(key: str, spec: Any) -> bool:
    """这个字段装的是不是另一个系统里的编号(任务号、fs_id、对象路径)—— 创作者写不出、认不出,画板上不摆。"""
    from app.domain.workflows import EXTERNAL_ID, config_data_type

    return isinstance(spec, dict) and config_data_type(key, spec) == EXTERNAL_ID


def content_outputs(meta: dict[str, Any]) -> list[str]:
    """落板的输出里算得上**内容**的那几个:素材,或点了名落板的文字。"""
    from app.domain.workflows import output_data_type

    named = {str(name) for name in meta.get("board_outputs") or ()}
    out = []
    for name in landing_outputs(meta):
        data_type = output_data_type(name, meta)
        if data_type == "asset" or (data_type == "text" and name in named):
            out.append(name)
    return out


#: 一个变换「跑一次会长出什么」的那几种格子。`asset` = 一份素材,但没说是哪一种。
OUTPUT_KINDS: tuple[str, ...] = ("note", "image", "video", "audio", "asset")


def output_kinds(meta: dict[str, Any]) -> list[str]:
    """跑一次落成哪几种格子,和 `content_outputs` 一一对应(同序)。

    ADR 0025 的 `output_kinds`:生成器挂在哪种空格子上(图片 / 视频 / 音频)、能力会在右边长出什么,
    都读这一份,不按工具名或输出名猜。文字落成便签;素材看节点的 `output_media`
    (`{输出名: image | video | audio}`,和输入字段的 `media` 同一个词表);没声明的,工具吃的那一种
    素材就是它吐的那一种(`board_group` 是 image / video / audio 时:降噪、抠图);再说不清就是
    `asset` —— 界面按最通用的媒体格(图片)画。
    """
    from app.domain.media_kinds import declared_media
    from app.domain.workflows import output_data_type

    declared = meta.get("output_media") if isinstance(meta.get("output_media"), dict) else {}
    group = board_group(meta)
    fallback = group if group in ("image", "video", "audio") else "asset"
    kinds = []
    for name in content_outputs(meta):
        if output_data_type(name, meta) == "text":
            kinds.append("note")
            continue
        media = declared_media(declared.get(name))
        kinds.append(media[0] if len(media) == 1 else fallback)
    return kinds


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


def content_transform_gap(meta: dict[str, Any], *, generation_has: Callable[[dict[str, Any]], bool] | None = None
                          ) -> str | None:
    """这个节点**差在哪儿**不是一个画板上的工具;是的话回 None。

    回的是原因的名字(给棘轮和测试说清楚为什么):
    `wiring`(流程 / 数据 / 知识库分组)、`needs_wiring`(必填一个只有搭流程的人看得懂的字段)、
    `no_content_output`(不交出素材,也没点名落板的文字)、`external_id`(按另一个系统里的编号去取东西:
    必填一个编号,或者不吃画板内容却收一个编号,见模块说明第 5 条)、`no_content_input`(不吃画板上的内容,
    又只交出文字)、`mirrored_by_generation`(它声明了和某个生成模型是同一件事,而 `generation_has`
    说点运行的人用得上那个模型 —— 画板上走生成那一个入口,见模块说明第 6 条)。
    """
    from app.domain.workflows import WIRING_CATEGORIES

    if meta.get("category") in WIRING_CATEGORIES:
        return "wiring"
    specs = meta.get("config") or {}
    if any(isinstance(spec, dict) and spec.get("required") and wiring_field(key, spec) for key, spec in specs.items()):
        return "needs_wiring"
    if not content_outputs(meta):
        return "no_content_output"
    external = [spec for key, spec in specs.items() if external_id_field(key, spec)]
    if any(spec.get("required") for spec in external) or (external and not _sinks(meta)):
        return "external_id"
    if not _makes_media(meta) and not _sinks(meta):
        return "no_content_input"
    mirror = meta.get("mirrors")
    if isinstance(mirror, dict) and generation_has is not None and generation_has(mirror):
        return "mirrored_by_generation"
    return None


def is_content_transform(meta: dict[str, Any], *, generation_has: Callable[[dict[str, Any]], bool] | None = None
                         ) -> bool:
    return content_transform_gap(meta, generation_has=generation_has) is None


#: 一个内容变换在画板上的角色(见模块说明):内容格的能力 / 空格子的一种填法。
ABILITY = "ability"
SLOT = "slot"
ROLES: tuple[str, ...] = (ABILITY, SLOT)

#: 画板上装素材的几种格子。
_MEDIA_KINDS: tuple[str, ...] = ("image", "video", "audio")
#: 宿主种类的先后(接口、测试按它排):文字的两种、媒体三种、3D 场景。
_HOST_ORDER: tuple[str, ...] = ("note", "document", *_MEDIA_KINDS, "scene")


def _host_fields(meta: dict[str, Any]) -> list[tuple[str, str]]:
    """这个变换**吃画板内容**的那几个字段 `(字段, 接的是什么)`,必填的在前、其余按声明的先后。

    素材 / 3D 场景字段优先:有它们的,文字字段是参数(出图的提示词),从上游便签接或手写。没有素材字段的:
    只交出文字的(翻译)吃的就是那段字;交出素材的(提示词出图)不吃内容 —— 空列表。
    """
    specs = meta.get("config") or {}
    sinks = _sinks(meta)
    fields = [(key, sink) for key, sink in sinks.items() if sink in ("asset", "scene")]
    if not fields and not _makes_media(meta):
        fields = list(sinks.items())
    return sorted(fields, key=lambda one: not (specs.get(one[0]) or {}).get("required"))


def board_role(meta: dict[str, Any]) -> str:
    """`ability`(内容格的能力)或 `slot`(空格子的一种填法)。只对过得了 content_transform_gap 的节点有意义。"""
    return ABILITY if _host_fields(meta) else SLOT


def board_hosts(meta: dict[str, Any]) -> tuple[str, ...]:
    """它挂在哪几种格子上。

    · 能力:它吃内容的那几个字段收得下的格子种类(`bindable_kinds`,字段的 `media` 说了只收哪几种素材的,
      就只挂那几种:转写挂音频和视频,转 GIF 只挂视频);
    · 填法:它产出的那种素材的空格子(output_kinds 里的图片 / 视频 / 音频);说不清产出哪种素材(`asset`)的,
      三种媒体格都能挑它 —— 回执按素材实际的种类落(见 canvas 的就地填),对不上宿主的新建在右边。
    """
    from app.domain.boards.tools import bindable_kinds

    fields = _host_fields(meta)
    if fields:
        specs = meta.get("config") or {}
        kinds = {kind for key, _sink in fields for kind in bindable_kinds(key, specs[key])}
    else:
        made = output_kinds(meta)
        kinds = {kind for kind in made if kind in _MEDIA_KINDS}
        if not kinds or "asset" in made:
            kinds = set(_MEDIA_KINDS)
    return tuple(kind for kind in _HOST_ORDER if kind in kinds)


def host_field(meta: dict[str, Any], kind: str) -> str | None:
    """能力挂在 `kind` 这种格子上时,宿主的内容填进哪个字段(第一个收得下它的,必填的在前)。填法没有这个字段。"""
    from app.domain.boards.tools import bindable_kinds

    specs = meta.get("config") or {}
    return next((key for key, _sink in _host_fields(meta) if kind in bindable_kinds(key, specs[key])), None)


def host_fields(meta: dict[str, Any]) -> dict[str, str]:
    """{宿主种类: 它的内容填进哪个字段}。接口发给界面和智能体:面板上这个字段不出现 —— 它**就是**宿主。"""
    if board_role(meta) != ABILITY:
        return {}
    return {kind: field for kind in board_hosts(meta) if (field := host_field(meta, kind))}


def host_sink(meta: dict[str, Any], field: str) -> str | None:
    """宿主填进的那个字段接的是哪种值(asset / scene / text)。"""
    return _sinks(meta).get(field)


def board_group(meta: dict[str, Any]) -> str:
    """它按吃什么内容归哪一组。声明了(`board_group`)就用声明的;没声明按它吃的内容推:

    接 3D 场景的归 3D;接素材的归那种素材(字段声明了 `media`,几个素材字段说的是同一种),
    说不清是哪种归「素材」;不吃素材、交出素材的(提示词出图)归「产出新素材」;剩下的吃文字吐文字。
    """
    declared = meta.get("board_group")
    if declared in BOARD_GROUPS:
        return str(declared)
    sinks = _sinks(meta)
    if "scene" in sinks.values():
        return "scene"
    from app.domain.workflows import config_media

    specs = meta.get("config") or {}
    media = [set(config_media(specs[key])) for key, sink in sinks.items() if sink == "asset"]
    if media:
        #: 一个字段没声明就是哪种都收;几个字段各说各的也分不到某一种 —— 都归「素材」。
        kinds = set.union(*media) if all(media) else set()
        return next(iter(kinds)) if len(kinds) == 1 else "asset"
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

    · 映射、原始 JSON、代码、子图(wiring_field)不出现,另一个系统里的编号(external_id_field)也不出现;
    · 模板字段在画板上就是一段字(`type: "text"`):画板上没有「上游的输出」可引用,上游是连进来的
      格子(`board_sources`),`{{…}}` 这种写法不该出现在创作者面前;
    · 说明里教 `{{…}}` 写法的那一句(写给工作流的)不带过来。
    """
    view: dict[str, Any] = {}
    for key, spec in config.items():
        if wiring_field(key, spec) or external_id_field(key, spec):
            continue
        field = dict(spec)
        if field.get("type") == "template":
            field["type"] = "text"
        if "{{" in str(field.get("description") or ""):
            field.pop("description", None)
        view[key] = field
    return view


__all__ = [
    "ABILITY",
    "BOARD_GROUPS",
    "ROLES",
    "SLOT",
    "board_hosts",
    "board_role",
    "host_field",
    "host_fields",
    "host_sink",
    "board_config_view",
    "board_description",
    "board_group",
    "content_outputs",
    "content_transform_gap",
    "external_id_field",
    "is_content_transform",
    "wiring_field",
]
