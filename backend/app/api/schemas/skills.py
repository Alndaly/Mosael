"""智能体技能的出入参(ADR 0040)。"""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from app.api.schemas.base import ApiModel


class AgentSkillOut(ApiModel):
    """列表里的一行。`ref` 是模型看到的名字(插件的带 `插件 id:`),界面也拿它当标识。"""

    ref: str
    name: str
    #: 显示名(`metadata.mosael-title`);没写就是 name。
    title: str
    description: str
    source: Literal["builtin", "workspace", "plugin"]
    #: 来源,说给人听的那一句(「Mosael 内置」「从 brand.zip 导入」「插件「ComfyUI」」)—— 插件名、导入自哪个文件都在这句里。
    source_label: str
    #: 工作区技能怎么来的:created / imported / conversation / copied / folder(扔进文件夹、没登记过的)。
    #: 界面据此判断「开之前要不要先看全文」。
    origin: str
    enabled: bool
    #: 只有工作区技能能改;内置和插件的只读(能复制成我的)。
    editable: bool
    #: 读不了 / 不能用的原因;空串 = 好的。有原因的开不了。
    problem: str = ""


class AgentSkillFileOut(ApiModel):
    path: str
    size: int
    #: 看起来像脚本(.py / .sh …):Mosael 不执行它,界面标出来。
    script: bool = False
    #: 文本文件的全文(审阅要看全文,ADR 0040 §6);二进制的为空、`binary` 为真。
    text: str | None = None
    binary: bool = False


class AgentSkillDetailOut(AgentSkillOut):
    license: str = ""
    compatibility: str = ""
    #: 实验性字段,只给人看:Mosael **不**因为它预先批准任何工具。
    allowed_tools: str = ""
    #: 规范之外的顶层字段(原样留在文件里,Mosael 不用)。
    unknown_fields: list[str] = Field(default_factory=list)
    #: `metadata` 里除显示名之外的那些(原样保留)。
    metadata: dict[str, str] = Field(default_factory=dict)
    body: str = ""
    files: list[AgentSkillFileOut] = Field(default_factory=list)


class AgentSkillWrite(ApiModel):
    """新建 / 改一个工作区技能:规范里的字段 + 显示名 + 正文。规则(名字的写法、长度)由格式包校验,这里只挡离谱的大小。"""

    name: str = Field(min_length=1, max_length=64)
    title: str = Field(default="", max_length=80)
    description: str = Field(min_length=1, max_length=1024)
    license: str = Field(default="", max_length=500)
    compatibility: str = Field(default="", max_length=500)
    body: str = Field(default="", max_length=64 * 1024)
    #: 从对话「存成技能」来的(只影响来源怎么写)。
    from_conversation: bool = False


class AgentSkillEnable(ApiModel):
    enabled: bool


class AgentSkillCopy(ApiModel):
    name: str = Field(min_length=1, max_length=64)


class AgentSkillImportFile(ApiModel):
    path: str
    size: int
    script: bool = False
    text: str | None = None
    binary: bool = False


class AgentSkillImportItem(ApiModel):
    name: str
    title: str = ""
    description: str = ""
    license: str = ""
    compatibility: str = ""
    allowed_tools: str = ""
    unknown_fields: list[str] = Field(default_factory=list)
    #: 它在压缩包 / 文件夹里原来那层目录叫什么(和 name 不同时界面提一句)。
    folder: str = ""
    #: 和已有技能撞名:"builtin"(内置的名字,必须改名)/ "workspace"(可以替换或改名)/ ""。
    conflict: str = ""
    files: list[AgentSkillImportFile] = Field(default_factory=list)


class AgentSkillImportOut(ApiModel):
    """暂存的导入,等人审阅。什么都还没装。"""

    import_id: str
    source_name: str = ""
    skills: list[AgentSkillImportItem]


class AgentSkillImportChoice(ApiModel):
    name: str
    #: 换个名字装(撞名、或者不喜欢原来的名字)。空 = 用原来的。
    rename_to: str = ""
    #: 装好就开。审阅过全文才勾得上(界面的事)。
    enable: bool = False
    #: 和已有的工作区技能撞名时替换它。
    replace: bool = False


class AgentSkillImportCommit(ApiModel):
    choices: list[AgentSkillImportChoice] = Field(min_length=1, max_length=20)


class AgentSkillDraftOut(ApiModel):
    """「存成技能」起草出来的东西:填进编辑表单,用户改完才保存。"""

    name: str
    title: str
    description: str
    body: str
