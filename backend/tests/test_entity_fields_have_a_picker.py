"""棘轮:**指向某样东西的节点字段给选择器,不给文本框。**

用户的原话是「有些应该是下拉选择而非输入吧」:画板上「渲染白模参考」的「3D 场景」和「镜头」
是两个文本框,要人去场景页把一串 id 抄回来,而旁边的「渲染内容」好好的是个下拉。同样的文本框
还有:时间线(九个节点)、轨道、项目、通用插件节点的连接。

字段装的是一个 id —— 场景、镜头、项目、时间线、轨道、账号、连接、工作流…… 那它就得在声明里
说清楚清单从哪来:`options_from`(后端 field_options 现查)、`options`(闭集)、`editor`(专用控件),
或者是素材字段(data_type 为 asset,表单给素材选择器)。认「这是一个 id」按两样:字段名
(`*_id` / `*_ids`,名字前半截是下面那张实体表里的一种)和推导出的数据类型(asset / sequence / scene)。

插件工具的入参(JSON Schema → 节点声明,见 plugins.nodes)一起查:随应用带的和示例插件的清单
都要过这一道 —— 插件节点和内置节点在表单上没有区别。

**另一个系统里的编号不是这个工作区里的东西**:ComfyUI 的任务号(`prompt_id`)、网盘的 `fs_id`、对象存储的
对象路径,清单只在那个系统里,给不出选择器。它们在声明里说清楚 —— `data_type: "external_id"`(插件写
`"format": "external_id"`,见 workflows.EXTERNAL_ID),不进豁免名单:画板靠同一句声明认出「按编号去外面
取东西」的工具。名字以 `_id` 结尾的字段(内置的和插件的)要么是下面那张实体表里的一种,要么这样声明过。

`EXEMPT` 是**说得出理由**的例外,只减不增。
"""

from __future__ import annotations

# 这条测试是一道**棘轮**:它进 docs/CONVENTIONS.md 的清单,由 scripts/sync-ratchet-docs.py 生成。
RATCHET = True

import json
import re
from pathlib import Path
from typing import Any

#: 值是「这个工作区里的某一样东西」的那几种实体。字段名 `<实体>_id(s)` 或 `<前缀>_<实体>_id(s)`。
_ENTITIES = (
    "asset", "scene", "shot", "note", "project", "sequence", "track", "clip", "workflow",
    "account", "profile", "instance", "voice", "model", "plugin",
)
_ENTITY_ID = re.compile(rf"(^|_)({'|'.join(_ENTITIES)})_ids?$")
_ENTITY_DATA_TYPES = frozenset({"asset", "sequence", "scene"})

#: 节点.字段 → 为什么它可以不带选择器。**只减不增。**
EXEMPT: dict[str, str] = {
    #: 和 provider / model 是**一次**选择:工作流检查器的生成专区从生成目录里挑一个模型,三格一起写
    #: (WorkflowsView 的 GENERATE_SPECIAL_CONFIG_KEYS),通用表单不渲染它。
    "ai_generate.provider_profile_id": "picked together with provider/model from the generation catalog",
    #: 片段是同一次运行里上游那一步刚放上去的(timeline_append.clip_id / generate_subtitles.clip_ids):
    #: 编辑那一刻列出来的,是这次运行要替掉的旧片段。值只该从上游接。
    "timeline_cut_ranges.clip_id": "clips come from the upstream step of the same run",
    "dub_subtitles.clip_ids": "clips come from the upstream step of the same run",
}

_REPO = Path(__file__).resolve().parents[2]


def _is_external(key: str, spec: dict[str, Any]) -> bool:
    from app.domain.workflows import EXTERNAL_ID, config_data_type

    return config_data_type(key, spec) == EXTERNAL_ID


def _is_entity(key: str, spec: dict[str, Any]) -> bool:
    from app.domain.workflows import config_data_type

    if _is_external(key, spec):
        return False
    return bool(_ENTITY_ID.search(key)) or config_data_type(key, spec) in _ENTITY_DATA_TYPES


def _has_picker(key: str, spec: dict[str, Any]) -> bool:
    from app.domain.workflows import config_data_type

    return bool(
        spec.get("options_from")
        or spec.get("options")
        or spec.get("editor")
        or spec.get("type") == "asset_list"
        # 素材字段:表单按数据类型给工作区素材的选择器(nodeForms/useNodeFieldOptions)。
        or config_data_type(key, spec) == "asset"
    )


def _plugin_tools() -> dict[str, dict[str, Any]]:
    """随应用带的和示例插件清单里声明的工具 → 它们在表单上的节点声明。"""
    from app.domain.plugins.nodes import node_meta

    found: dict[str, dict[str, Any]] = {}
    for manifest in sorted((_REPO / "plugins").glob("*/*/mosael.plugin.json")):
        data = json.loads(manifest.read_text(encoding="utf-8"))
        tools = data.get("tools") if isinstance(data.get("tools"), dict) else {}
        for tool in tools.get("declare") or []:
            if not isinstance(tool, dict) or not tool.get("input_schema"):
                continue
            meta = node_meta({**tool, "instance_id": "i", "instance_name": data.get("name", ""),
                              "package_id": data["id"]})
            found[f"plugin.{data['id']}.{tool['name']}"] = meta
    return found


def _registry() -> dict[str, dict[str, Any]]:
    from app.domain.workflows import NODE_TYPES

    return {**NODE_TYPES, **_plugin_tools()}


def test_指向某样东西的字段都有选择器() -> None:
    offenders = [
        f"{name}.{key}"
        for name, meta in _registry().items()
        for key, spec in (meta.get("config") or {}).items()
        if isinstance(spec, dict) and _is_entity(key, spec) and not _has_picker(key, spec)
        and f"{name}.{key}" not in EXEMPT
    ]
    assert not offenders, (
        "这些字段装的是一个 id,却是让人手抄的文本框 —— 在声明里写上清单从哪来"
        "(options_from / options / editor),实在不该有的写进 EXEMPT 并说明理由:\n"
        + "\n".join(f"  {one}" for one in offenders)
    )


def test_每个以_id_结尾的字段都归了类() -> None:
    """实体表要是漏了一种,上面那条就对它睁一只眼。新加的 `xxx_id` 字段得先想清楚它指向什么:这个工作区里的
    一种东西(进实体表、给选择器),还是另一个系统里的编号(声明 external_id)。插件清单一起查 —— 此前
    `prompt_id` / `fs_id` 不在实体表里,于是悄悄漏过,画板也就认不出「按任务号取回」不是内容变换。"""
    unknown = sorted(
        f"{name}.{key}"
        for name, meta in _registry().items()
        for key, spec in (meta.get("config") or {}).items()
        if re.search(r"_ids?$", key) and not _ENTITY_ID.search(key)
        and not (isinstance(spec, dict) and _is_external(key, spec))
    )
    assert not unknown, (
        "这些字段名看着是 id,却既不在 _ENTITIES 里、也没声明是另一个系统里的编号"
        f"(data_type / format: external_id):{unknown}"
    )


def test_插件清单确实被查到了() -> None:
    """扫描范围要是悄悄变空(清单挪了地方、形状改了),上面那条会对插件永远通过。"""
    tools = _plugin_tools()
    assert len(tools) >= 5, sorted(tools)
    assert any(key == "asset_id" for meta in tools.values() for key in meta["config"]), "至少有一个插件工具收素材"


def test_豁免名单里没有过期的条目() -> None:
    """豁免的字段要是已经有了选择器、或者已经不存在,就该划掉。"""
    registry = _registry()
    stale = sorted(
        entry for entry in EXEMPT
        if (spec := (registry.get(entry.rsplit(".", 1)[0], {}).get("config") or {}).get(entry.rsplit(".", 1)[1])) is None
        or _has_picker(entry.rsplit(".", 1)[1], spec)
    )
    assert not stale, f"这些豁免已经过期,从 EXEMPT 里删掉:{stale}"


def test_留空取唯一一项的字段都有清单() -> None:
    """`sole_option_default` 说的是「清单里只有一项时就是它」—— 没有清单的字段这么写没有意义。"""
    from app.domain.workflows.field_options import SOURCES

    wrong = sorted(
        f"{name}.{key}"
        for name, meta in _registry().items()
        for key, spec in (meta.get("config") or {}).items()
        if isinstance(spec, dict) and spec.get("sole_option_default") and spec.get("options_from") not in SOURCES
    )
    assert not wrong, wrong
