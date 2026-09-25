"""节点注册表的**出口形状**:一份注册表(NODE_TYPES + 插件节点)→ 给界面看的节点类型清单。

注册表里存的是 key 和声明(见 workflows.NODE_TYPES、plugins.nodes);这里把它们翻成请求方的
语言、给每个字段贴上推导出的语义类型、按面板分组排好。**只有这一处**做这件事:工作流的节点
面板和创意画板的工具清单读的是同一份描述,同一个节点不会在两处叫两个名字。
"""

from __future__ import annotations

from typing import Any

from app.core.i18n import MESSAGES, t
from app.domain.workflows import (
    NODE_CATEGORIES,
    config_data_type,
    config_editor,
    config_label,
    output_data_type,
    output_label,
)


def describe_node_types(registry: dict[str, dict[str, Any]], locale: str) -> list[dict[str, Any]]:
    """一份节点注册表 → 给界面的节点类型清单:**按面板分组顺序排好**、按 `locale` 翻好。

    工作流的节点面板用它,创意画板列「能跑的工具」也要用它 —— 标签是 i18n key、分组靠
    NODE_CATEGORIES 排序,两处各翻各排的话,同一个节点会在两个地方叫两个名字、排在两个位置。

    排序放在这里而不是前端:分组和顺序是这份注册表自己的性质(NODE_CATEGORIES 就在它旁边)。
    让前端再排一次,等于把同一份知识抄成两份 —— 加一个分组时忘了改另一边,新节点就会静默
    掉进"其它"里,而没有任何东西会报错。

    目录里存 key,**出口才翻** —— 和发布平台目录、TTS 引擎目录同一条(见 core/i18n)。
    """
    order = {name: index for index, name in enumerate(NODE_CATEGORIES)}
    items = [
        {
            "type": key,
            "label": t(meta["label"], locale),
            "description": t(meta["description"], locale),
            #: 翻**这里**、排序**在下面按 key** —— 顺序是这份注册表的性质,不该跟着语言变。
            #: 先翻再排的话,order 表拿翻译后的字去查 key,一个都对不上,所有节点静默掉进末尾。
            "category": t(meta.get("category", ""), locale),
            "category_key": meta.get("category", ""),
            # 每个配置字段带上**它装的是什么**(素材/时间线/…)。界面据此决定给不给素材选择器、
            # 画不画缩略图、连线时类型对不对得上 —— 此前这份知识是前端自己抄的一张表,
            # 「素材」节点本身就漏了,而插件节点它永远也覆盖不到。
            "config": {key: translated_spec(key, with_data_type(key, spec), locale) for key, spec in meta["config"].items()},
            "outputs": list(meta["outputs"]),
            "output_types": {output: output_data_type(output, meta) for output in meta["outputs"]},
            # 英文键留给连线/导出,翻译后的名字留给人;两者不再混成一个字段。
            "output_labels": {output: t(output_label(output, meta), locale) for output in meta["outputs"]},
            "plugin_name": meta.get("plugin_name", ""),
            "tool_name": meta.get("tool_name", ""),
            # 内嵌子图节点体内看得见的作用域名 —— 画布就绪检查和后端校验读同一格(见 NESTED_BODY_TYPES)。
            "body_scope": {root: list(fields) for root, fields in (meta.get("body_scope") or {}).items()},
        }
        for key, meta in registry.items()
    ]
    # 组内保持注册表里的声明顺序(sorted 是稳定的)。
    ordered = sorted(items, key=lambda item: order.get(item["category_key"], len(order)))
    for item in ordered:
        item.pop("category_key", None)  # 排序用的,不该出现在响应里
    return ordered


def with_data_type(key: str, spec: Any) -> Any:
    """把推导出的语义类型贴到字段声明上;推不出来就原样返回。"""
    if not isinstance(spec, dict):
        return spec
    enriched = dict(spec)
    data_type = config_data_type(key, spec)
    if data_type:
        enriched["data_type"] = data_type
    # 界面上叫什么,也随声明一起发 —— 前端此前自己抄了一张表,81 个键只覆盖了 28 个,
    # 剩下的在中文界面上直接露出英文键名。
    label = config_label(key, spec)
    if label:
        enriched["label"] = label
    # 这个字段的值跟着谁走 —— 父字段一换,这里存的旧值就失效了(换了供应商配置,模型还是
    # 上一家的那个)。声明在后端,是因为**插件节点也有这种关系**,前端一张写死的表覆盖不到。
    depends_on = str(spec.get("depends_on") or "").strip()
    if depends_on:
        enriched["depends_on"] = depends_on
    # 选项要现查的字段:来源名随声明发下去,前端对所有这种字段走同一个接口(见 field_options)。
    options_from = str(spec.get("options_from") or "").strip()
    if options_from:
        enriched["options_from"] = options_from
    # 清单之外还能手填吗。模型名就是这种:新模型上线往往早于目录更新,只给下拉会把人堵死在
    # 「列表里没有,于是填不进去」的死角。**由声明说了算**,不由前端按字段名猜(此前是 key === "model")。
    if spec.get("allow_custom"):
        enriched["allow_custom"] = True
    # object 字段用哪种编辑器:一行一对的映射,还是原始 JSON。
    editor = config_editor(key, spec)
    if editor:
        enriched["editor"] = editor
    return enriched


def translated_spec(key: str, spec: dict, locale: str) -> dict:
    """翻一个配置字段的说明。

    **有几条说明是现算的**(可用角色、可用生成参数、可用时间线算子)——它们的列表来自各自的
    产地,加一种就该跟着变。所以领域给的是 key + 参数,句子在这里按语言组装:两种语言同时
    跟着那张表走,而不是只有中文那句变。
    """
    out = dict(spec)
    #: label 和 description 都是 key。label 那张表按**键名**登记(selector 在六种浏览器节点里
    #: 是同一个意思),所以翻在这里而不是在表里 —— 表只管「这个键叫什么」。
    if isinstance(out.get("label"), str):
        out["label"] = t(out["label"], locale)
    if isinstance(out.get("description"), str):
        out["description"] = t(out["description"], locale, **(out.get("description_params") or {}))
    #: 参数是给翻译用的,不该出现在响应里(和 core/i18n 的 PARAMS_FIELD 同一个道理)。
    out.pop("description_params", None)
    #: 下拉里的每一项也是给人看的。**值照旧是英文的**(存进 config、执行体认的是它),
    #: 名字按语言翻 —— 此前界面上直接摆着 `duck` / `separate`,中文界面里也是这样。
    #: 键名是 `wfOpt_<字段>_<值>`,回落到各字段通用的 `wfOpt__<值>`(是/否),再回落到值本身
    #: (插件节点的选项没有登记处,照原样显示)。
    if isinstance(out.get("options"), list):
        out["option_labels"] = {str(option): option_label(key, str(option), locale) for option in out["options"]}
    return out


#: 这些字段的选项是专业术语,原样显示比翻译清楚(HTTP 方法)。
LITERAL_OPTION_FIELDS = frozenset({"method"})


def option_label(field: str, value: str, locale: str) -> str:
    """下拉里这一项显示成什么。见 translated_spec 的说明。"""
    if field in LITERAL_OPTION_FIELDS:
        return value
    for key in (f"wfOpt_{field}_{value}", f"wfOpt__{value}"):
        if key in MESSAGES:
            return t(key, locale)
    return value


__all__ = ["LITERAL_OPTION_FIELDS", "describe_node_types", "option_label", "translated_spec", "with_data_type"]
