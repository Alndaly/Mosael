"""插件报的一个模型、一个工具**是哪样东西的哪个入口**(`group`,ADR 0045)。

ComfyUI 的一张工作流有一个「完整工作流」入口和它上面每张表单各一个入口:目录里各是一个模型、一个工具,名字是各自的
(表单标题 / 文件名)。它们来自同一张工作流这件事放在 `group` 里,不拼进名字 —— 宿主据此把同一组的几项排在一起、
第二行写「来自 krea2-text-2-image」,搜文件名也搜得到:

    "group": {"id": "krea2-text-2-image.json", "label": "krea2-text-2-image", "entry": "form"}

- `id`:那样东西的编号(同一组的几项这一格相同);
- `label`:它自己的名字,可以按语言分(`{"zh", "en"}`,给人看时再挑);
- `entry`:`full` 是这样东西本身(全部参数),`form` 是它上面的一张表单。

宿主不认识「工作流」,只认「同一组」「本身 / 表单」。形状不对的整条不认(当没说),不让一条坏数据把一项藏起来。
"""

from __future__ import annotations

from typing import Any

from app.core.i18n import pick_text

#: 认的入口种类。
ENTRIES = ("full", "form")
#: 编号、名字最长多少。编号是 ComfyUI 的工作流路径,和模型 id 一样长。
_MAX_ID = 600
_MAX_LABEL = 200


def clean_group(raw: Any) -> dict[str, Any] | None:
    """插件说的 `group` 收成规整的形状;认不出就是 None。名字按语言分的原样留着。"""
    if not isinstance(raw, dict):
        return None
    group_id = raw.get("id")
    entry = raw.get("entry")
    if not isinstance(group_id, str) or not group_id.strip() or len(group_id) > _MAX_ID or entry not in ENTRIES:
        return None
    label = raw.get("label")
    if isinstance(label, dict):
        label = {str(lang)[:16]: one.strip()[:_MAX_LABEL] for lang, one in label.items() if isinstance(one, str) and one.strip()}
    elif isinstance(label, str):
        label = label.strip()[:_MAX_LABEL]
    if not label:
        return None
    return {"id": group_id.strip(), "label": label, "entry": entry}


def readable_group(group: Any, locale: str | None = None) -> dict[str, str] | None:
    """给人看的样子:名字按看的人的语言挑好(清单在后台刷新,那一刻的语言不是看的人的)。不拼成一句 ——
    「来自 X · 连接名」怎么摆是界面的事。"""
    if not isinstance(group, dict) or not group.get("id"):
        return None
    return {"id": str(group["id"]), "label": pick_text(group.get("label"), locale) or str(group["id"]),
            "entry": str(group.get("entry") or "full")}


__all__ = ["ENTRIES", "clean_group", "readable_group"]
