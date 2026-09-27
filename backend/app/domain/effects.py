"""一个动作**后果落在哪儿** —— 智能体替人做它之前要不要先问一声,就看这一个词。

**词表本身**(none / paid / external / local-code,以及插件工具没声明时按 external 算)属于插件清单
格式,住在 `mosael_formats.effects`(桌面后端与社区服务共用,ADR 0026);这里接过来,再加上桌面端
自己的那一半:开不开确认卡、归哪一档权限、卡上那半句怎么说。三处在用它,说的是同一件事:

· 插件清单里每个工具的 `effects`(见 docs/PLUGIN_MANIFEST 的「确认」一节,domain/plugins);
· 画板产出者的 `effects`(见 domain/boards/producers,ADR 0021 决定 2);
· 智能体调用它们时开不开确认卡、按哪一档开(见 domain/agent/confirmable 的 plugin_tools 与
  automation.run_board_item)。

此前画板有一份 `none / paid / external`,插件只有一个 `read_only`,两边各自把「插件工具要不要问人」
推一遍 —— 画板说「不只读就是 external」,智能体那条路却直接跑。同一个工具从画板上跑要卡、从对话里
跑不要,用户没法知道哪条是真的。现在只有这一份:

    none        不花钱、不出门:只读,或者只往 Mosael 自己里面写(收进素材库之类)。直接跑。
    paid        会花钱或占付费算力(按次计费的接口、生成)。要确认卡,归 ai-cost 那一档。
    external    后果在 Mosael 之外、撤不回:上传到别人的服务器、改别处的数据、对外发送。
                要确认卡,归 external 那一档。
    local-code  会在这台电脑上执行一段**调用方写的代码**。要确认卡,归 external 那一档
                (那一档的定义本来就含「本机跑过的代码」),卡上单独点明。
"""

from __future__ import annotations

from mosael_formats.effects import (
    EFFECTS,
    EXTERNAL,
    LOCAL_CODE,
    NONE,
    PAID,
    PLUGIN_DEFAULT,
    plugin_tool_effects,
)

#: 每种后果开卡时归哪一档权限(confirmable/registry.PERMISSIONS 里的名字)。
#: none 不在表里:它不开卡。
_PERMISSION = {PAID: "ai-cost", EXTERNAL: "external", LOCAL_CODE: "external"}

#: 卡上那半句「为什么要你看一眼」的文案 key(core/i18n)。
_WARNING = {PAID: "confirm_effectPaid", EXTERNAL: "confirm_effectExternal", LOCAL_CODE: "confirm_effectLocalCode"}


def needs_card(effects: object) -> bool:
    """这种后果要不要先问人。**不认识的取值一律要问** —— 一个拼错的字符串不该等于放行。"""
    return effects != NONE


def permission_for(effects: object) -> str | None:
    """开卡归哪一档。none → None(不开卡);不认识的按 external 算,理由同上。"""
    if effects == NONE:
        return None
    return _PERMISSION.get(str(effects), _PERMISSION[EXTERNAL])


def warning_key(effects: object) -> str:
    """卡上点明后果的那半句;none 没有。"""
    if effects == NONE:
        return ""
    return _WARNING.get(str(effects), _WARNING[EXTERNAL])


__all__ = [
    "EFFECTS",
    "EXTERNAL",
    "LOCAL_CODE",
    "NONE",
    "PAID",
    "PLUGIN_DEFAULT",
    "needs_card",
    "permission_for",
    "plugin_tool_effects",
    "warning_key",
]
