"""一个动作**后果落在哪儿**的词表 —— 插件清单里每个工具的 `effects` 只能写这几个词。

    none        不花钱、不出门:只读,或者只往 Mosael 自己里面写(收进素材库之类)。
    paid        会花钱或占付费算力(按次计费的接口、生成)。
    external    后果在 Mosael 之外、撤不回:上传到别人的服务器、改别处的数据、对外发送。
    local-code  会在这台电脑上执行一段**调用方写的代码**。

词表属于清单格式,所以住在这里:桌面后端(智能体开不开确认卡、按哪一档开,见
backend/app/domain/effects.py)、插件市场索引的生成脚本、社区服务的 `/plugins/index.json` 都按它算。

**插件工具没声明时按 external 算**:插件跑的是别人的代码,「不知道」要落在保守那一边。
"""

from __future__ import annotations

NONE = "none"
PAID = "paid"
EXTERNAL = "external"
LOCAL_CODE = "local-code"

#: 认得的全部取值。顺序即「由轻到重」,给文档和界面列举用。
EFFECTS = (NONE, PAID, EXTERNAL, LOCAL_CODE)

#: 插件工具**没说**的时候按哪个算。
PLUGIN_DEFAULT = EXTERNAL


def plugin_tool_effects(*, read_only: bool, declared: object = None, default: object = None) -> str:
    """一个插件工具**实际**的后果:只读就是 none;否则按工具自己声明的、再按包上的缺省,都没有就 external。

    清单解析时已经把「只读却声明了别的后果」判成错(见 plugin_manifest);这里只做取值,不再判一遍。
    """
    if read_only:
        return NONE
    for candidate in (declared, default):
        if candidate in EFFECTS:
            return str(candidate)
    return PLUGIN_DEFAULT


__all__ = ["EFFECTS", "EXTERNAL", "LOCAL_CODE", "NONE", "PAID", "PLUGIN_DEFAULT", "plugin_tool_effects"]
