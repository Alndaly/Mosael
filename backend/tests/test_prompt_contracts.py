"""Prompt 的硬约束要能被看见,不能只活在维护者的记忆里。

不是测某一句文案,而是测每个高风险入口仍包含它赖以正确的契约:
标识符怎么引用、事实从哪里来、看不清时该说什么、输出是不是被结构约束。
"""

from __future__ import annotations

from app.domain.agent.prompt import SYSTEM_PROMPT_TEMPLATE
from app.domain.agent.skills import runtime as skills_runtime
from app.domain.analysis.service import ANALYSIS_SYSTEM
from app.domain.publish.copy import _SYSTEM as COPY_SYSTEM


def test_主提示没有裸插件技能示例且技能目录给出精确格式() -> None:
    assert "dev.mosael.comfyui" not in SYSTEM_PROMPT_TEMPLATE, "主提示不应把插件技能写成裸名"
    assert "逐字照抄" in skills_runtime._HEADER
    assert "插件 id:技能名" in skills_runtime._HEADER


def test_技能目录再次强调插件引用格式() -> None:
    assert "逐字照抄" in skills_runtime._HEADER
    assert "插件 id:技能名" in skills_runtime._HEADER


def test_素材分析区分观察与推断且不补看不见的细节() -> None:
    assert "区分" in ANALYSIS_SYSTEM and "推断" in ANALYSIS_SYSTEM
    assert "直接说不知道" in ANALYSIS_SYSTEM
    assert "不要编造" in ANALYSIS_SYSTEM


def test_发布文案带平台约束与事实边界() -> None:
    assert "不编造" in COPY_SYSTEM
    assert "平台" in COPY_SYSTEM and "标题上限" in COPY_SYSTEM
    assert "标签 3–8 个" in COPY_SYSTEM
