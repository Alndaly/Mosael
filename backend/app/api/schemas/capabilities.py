"""宿主能力由谁提供(设置 → 能力提供方,ADR 0031 §5)的出入参。领域在 domain/capabilities。"""

from __future__ import annotations

from pydantic import Field

from app.api.schemas.base import ApiModel


class CapabilityUseOut(ApiModel):
    """一项宿主能力用在哪(ADR 0032 §4),从能力表现算。"""

    #: `app`(宿主界面上的入口)/ `workflow`(工作流或画板的节点字段)/ `agent`(智能体工具)。
    kind: str
    label: str


class CapabilityProviderOut(ApiModel):
    """一项宿主能力的一个候选:内置实现(`builtin`),或这个人的一个插件连接。"""

    id: str
    name: str
    builtin: bool = False
    #: 还缺哪些必填项;空 = 配好了,选得了。
    missing: list[str] = Field(default_factory=list)


class CapabilityChoicesOut(ApiModel):
    """「设置 → 能力提供方」里的一项(ADR 0031 §5)。"""

    capability: str
    label: str
    description: str = ""
    #: 我定的那一家;没定是 None。
    current: str | None = None
    #: 不定的话会用的那一家(有内置实现就是它;没有的只有一家配好时才有),和现在定没定无关。
    automatic: str | None = None
    options: list[CapabilityProviderOut] = Field(default_factory=list)
    used_by: list[CapabilityUseOut] = Field(default_factory=list)


class CapabilityDefaultUpdate(ApiModel):
    #: 定哪一家;None(或内置实现的 id)= 不定。
    provider_id: str | None = None
