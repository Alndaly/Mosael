from __future__ import annotations

from datetime import datetime

from pydantic import Field

from app.api.schemas.base import ApiModel, OrmModel
from app.api.schemas.workflows import WorkflowNodeTypeOut


class BoardOut(OrmModel):
    id: str
    workspace_id: str
    name: str
    canvas: dict
    revision: int
    created_at: datetime
    updated_at: datetime


class BoardCreate(ApiModel):
    workspace_id: str
    name: str = ""
    canvas: dict | None = None


class BoardDuplicate(ApiModel):
    workspace_id: str
    #: 副本叫什么。「× 副本」是界面语言里的一句话,由前端按当前语言拼好;留空就沿用原名。
    name: str = ""


class BoardUpdate(ApiModel):
    workspace_id: str
    #: 调用方看到的是哪一版。**必填**:一份不带版本的快照存回来,会盖掉服务端在它之后落下的东西
    #: (回执填回的产出、别人的编辑)而不报冲突。
    base_revision: int = Field(ge=1)
    #: 两者都可以单独传 —— 自动保存只发 canvas,重命名只发 name。None = 这次不改它。
    name: str | None = None
    canvas: dict | None = None


class BoardRun(ApiModel):
    """在画板上跑一个产出者(生成、写字、念出来、截一段……),产出落回 `item_id` 那一格。

    `form` 是这个产出者自己的表单,形状由它声明、在领域里校验(见 domain/boards/producers)——
    这里不为每个产出者各开一个请求体。
    """

    workspace_id: str
    #: 调用方看到的是哪一版。在**起任务之前**问:之后才发现冲突的话,钱已经花了。
    base_revision: int = Field(ge=1)
    #: 前端先编好 id —— 占位项和回执要指同一个东西,由前端定名字省掉一次往返。
    item_id: str
    #: 宿主那一格的种类,必须是这个产出者能挂的。
    kind: str
    x: float = 0
    y: float = 0
    producer: str
    form: dict = Field(default_factory=dict)


class BoardProducerOut(WorkflowNodeTypeOut):
    """画板上的一个产出者:节点描述(和工作流节点面板同一份)+ 画板自己的几样(见 boards.producers.describe)。

    `type` 是节点类型(内置的就是它们自己的名字),字段选项接口认它;`id` 是产出者的名字,
    存在一格的 `form.producer`(它自己的产出者)或 `form.abilities` 的键(它的一项能力)上、跑的时候发的是它。
    配置字段里多一样 `board_sources`:这个字段能接哪几种上游格子。
    """

    id: str
    #: 能挂在哪几种格子上(画板项的 kind)。
    hosts: list[str]
    #: `slot`:一格自己的产出者(写在 `form.producer`,空格子怎么被填);`ability`:内容格的一项能力(设置存在
    #: `form.abilities[id]`,宿主的内容就是输入,产出新建在右边)。见 boards.transforms.board_role。
    role: str = "slot"
    #: 能力:{宿主种类: 宿主的内容填进哪个字段}。那个字段在面板上不出现 —— 它就是宿主。别的产出者是空的。
    host_fields: dict[str, str] = Field(default_factory=dict)
    permission: str
    #: "none" | "paid" | "external" —— 智能体替人跑时要不要确认卡。
    effects: str
    #: 能不能挑来填一个空槽(一种格子有几个这样的产出者时,面板上给一个切换)。
    fills_empty_slot: bool = False
    #: 这个产出者存着的表单就是一次运行发的那一份(节点产出者 —— 能力、空格子上的生成器 —— 和 3D 场景格渲白模):
    #: 智能体能照它替人填(edit_board 的 set_form)、替人点运行(run_board_item)。
    runs_from_draft: bool = False
    #: 节点产出者按它吃的是什么内容归哪一组(new / image / video / audio / text / scene / asset,见
    #: boards.transforms.BOARD_GROUPS),不是工作流面板的分组;能力图标认不出时按它兜底。内置的是空串。
    board_group: str = ""
    #: 那一组给人看的名字(按请求的语言翻好)。
    board_group_label: str = ""
    #: 给创作者看的一句说明 —— 不是工作流节点那段写给搭流程的人的说明。
    board_description: str = ""
    #: 跑一次会产出哪几种格子(note / image / video / audio / asset,boards.transforms.output_kinds;
    #: ADR 0025)。生成器挂在其中那几种媒体的空格子上。内置的是空列表。
    output_kinds: list[str] = Field(default_factory=list)
