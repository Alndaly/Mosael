"""智能体技能的出入参(ADR 0040)。"""

from __future__ import annotations

from app.api.schemas.base import ApiModel


class AgentSkillOut(ApiModel):
    """列表里的一行。`ref` 是模型看到的名字(插件的带 `插件 id:`),界面也拿它当标识。"""

    ref: str
    #: 显示名(`metadata.mosael-title`);没写就是 name。
    title: str
    description: str
    #: 来源,说给人听的那一句(「Mosael 内置」「从 brand.zip 导入」「插件「ComfyUI」」)。
    source_label: str
    enabled: bool
    #: 读不了 / 不能用的原因;空串 = 好的。
    problem: str = ""
